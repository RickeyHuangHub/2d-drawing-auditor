"""冒烟测试 - 从项目根目录运行: python smoke_test.py"""
import sys
sys.path.insert(0, '.')

from main import app
from fastapi.testclient import TestClient

client = TestClient(app)
passed = 0
failed = 0

def test(name, condition):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")

print("=== 2D图纸审核高手 - 冒烟测试 ===\n")

# API 测试
print("[API 端点]")
r = client.get('/api/config')
test("GET /api/config 返回 200", r.status_code == 200)
data = r.json()
test("配置包含 9 项检查项", len(data["default_checklist"]) == 9)
test("模型名称正确", data["model"] == "doubao-vision-pro-32k")

r = client.get('/api/checklist')
test("GET /api/checklist 返回 200", r.status_code == 200)

r = client.get('/api/rules')
test("GET /api/rules 返回 200", r.status_code == 200)
rules_data = r.json()
test("Baseline V1.0 共 28 条规则", sum(len(c["rules"]) for c in rules_data["categories"]) == 28)
test("规则库含 7 大类", len(rules_data["categories"]) == 7)
test("规则库含 6 种 finding_type",
     len(rules_data["finding_types"]) == 6)
test("全局审核原则存在", "DRAWING AUDIT EXPERT" in rules_data["instruction"])

r = client.get('/api/tasks')
test("GET /api/tasks 返回 200", r.status_code == 200)

r = client.get('/')
test("GET / 返回前端页面", r.status_code == 200 and "2D图纸审核高手" in r.text)

r = client.post('/api/tasks', json={'folder_path': 'C:/nonexistent'})
test("不存在的文件夹返回 404", r.status_code == 404)

# 模块导入测试
print("\n[模块导入]")
try:
    from backend.pdf_processor import PDFProcessor, scan_pdf_folder
    test("pdf_processor 导入成功", True)
except Exception as e:
    test(f"pdf_processor 导入: {e}", False)

try:
    from backend.rule_checker import RuleChecker
    test("rule_checker 导入成功", True)
except Exception as e:
    test(f"rule_checker 导入: {e}", False)

try:
    from backend.ai_auditor import AIAuditor
    test("ai_auditor 导入成功", True)
except Exception as e:
    test(f"ai_auditor 导入: {e}", False)

try:
    from backend.report_writer import ReportWriter
    test("report_writer 导入成功", True)
except Exception as e:
    test(f"report_writer 导入: {e}", False)

try:
    from backend.task_manager import TaskManager
    test("task_manager 导入成功", True)
except Exception as e:
    test(f"task_manager 导入: {e}", False)

try:
    from backend.rule_engine import RuleEngine, parse_hole_pairs, build_finding
    test("rule_engine 导入成功", True)
except Exception as e:
    test(f"rule_engine 导入: {e}", False)

# Baseline 规则库与确定性引擎测试
print("\n[Baseline 规则库]")
from config import EFFECTIVE_RULES, get_enabled_rules, get_effective_rule
test("有效规则集共 28 条", len(EFFECTIVE_RULES) == 28)
enabled = get_enabled_rules(["title_block", "dimension", "tolerance",
                             "views", "features", "tech_req", "drafting", "revision"])
test("默认勾选启用 28 条规则", len(enabled) == 28)
test("DFM-002 默认深径比阈值 5.0",
     get_effective_rule("DFM-002")["parameters"]["maximum_hole_depth_ratio"] == 5.0)
test("TOL-003 finding_type 为 COST_RISK",
     get_effective_rule("TOL-003")["finding_type"] == "COST_RISK")

print("\n[确定性规则引擎]")
engine = RuleEngine(enabled)
det_findings = engine.run("图号: ABC-001-A\nØ3 深22\nØ8 深25\n技术要求: GB/T 1804-m")
deep_holes = [f for f in det_findings if f.rule_id == "DFM-002"]
test("深孔 Ø3 深22 → L/D 7.33 > 5 触发 DFM-002", len(deep_holes) == 1)
test("DFM-002 含计算与证据", bool(deep_holes and deep_holes[0].calculation.get("value") == 7.333))
test("DFM-002 finding_type 为 MANUFACTURING_RISK",
     deep_holes[0].finding_type == "MANUFACTURING_RISK")
test("Ø8 深25 → L/D 3.125 < 5 不触发",
     not any(f.rule_id == "DFM-002" and "8.0" in str(f.calculation) for f in det_findings))

# 规则检查器功能测试（含 Baseline 规则 ID 映射）
print("\n[规则检查器功能]")
checker = RuleChecker()
sample = "图号: ABC-001-A\n版本: Rev B\n材料: 304不锈钢\n设计: 张三\n审核: \n批准: 李四\n未注公差按 GB/T 1804-m\n"
issues, info = checker.run(sample)
test("能提取图号", info.get("drawing_number") == "ABC-001-A")
test("能提取版本", info.get("revision") == "B")
test("能提取材料", "304" in info.get("material", ""))
test("空签名栏检测为阻断级", any(i.severity.value == "block" and "签名" in i.title for i in issues))
test("缺少未注公差不报错（已包含）", not any("未注公差" in i.title for i in issues))
test("图号缺失映射为 DOC-001", all(
    not (i.title == "未找到图号/物料编码" and i.rule_id != "DOC-001") for i in issues))

# 数据模型测试
print("\n[数据模型]")
from backend.models import FileAuditResult, Severity, AuditStatus, FindingType
fr = FileAuditResult(file_path="/test/a.pdf", file_name="a.pdf")
test("FileAuditResult 创建成功", fr.file_name == "a.pdf")
test("默认状态为 pending", fr.status == AuditStatus.PENDING)
test("FindingType 枚举含 DRAWING_ERROR", FindingType.DRAWING_ERROR.value == "DRAWING_ERROR")

print(f"\n=== 结果: {passed} 通过, {failed} 失败 ===")
sys.exit(0 if failed == 0 else 1)
