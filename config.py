"""
2D图纸审核高手 - 全局配置
"""
import os
import sys
from pathlib import Path
from copy import deepcopy

# 项目根目录
BASE_DIR = Path(__file__).parent.resolve()
DATA_DIR = BASE_DIR / "data"
FRONTEND_DIR = BASE_DIR / "frontend"
DATA_DIR.mkdir(exist_ok=True)

# 加载自定义规则（如果存在）
try:
    sys.path.insert(0, str(BASE_DIR))
    from custom_rules import (
        CUSTOM_CHECKLIST,
        CUSTOM_TECH_REQS,
        CUSTOM_RULE_CHECKS,
        CUSTOM_TITLE_BLOCK_FIELDS,
        CUSTOM_OVERRIDES,
        CUSTOM_BASELINE_RULES,
    )
except ImportError:
    CUSTOM_CHECKLIST = []
    CUSTOM_TECH_REQS = []
    CUSTOM_RULE_CHECKS = []
    CUSTOM_TITLE_BLOCK_FIELDS = {}
    CUSTOM_OVERRIDES = []
    CUSTOM_BASELINE_RULES = []

# 加载 Baseline V1.0 规则库
try:
    from baseline_rules import (
        BASELINE_RULES,
        RULE_CATEGORIES,
        FINDING_TYPES,
        FINDING_TYPE_LABEL_ZH,
        SEVERITY_MAP,
        BASELINE_INSTRUCTION,
        get_rule,
    )
except ImportError:
    BASELINE_RULES = []
    RULE_CATEGORIES = []
    FINDING_TYPES = []
    FINDING_TYPE_LABEL_ZH = {}
    SEVERITY_MAP = {}
    BASELINE_INSTRUCTION = ""
    get_rule = lambda x: None

# 企业覆盖参数与严重度（Baseline Rule → Override）
def _apply_overrides(rules):
    """将 CUSTOM_OVERRIDES 应用到规则副本，生成有效规则集"""
    effective = []
    for rule in rules:
        r = deepcopy(rule)
        for ov in CUSTOM_OVERRIDES:
            if ov.get("rule_id") == r["id"]:
                param = ov.get("parameter")
                if param and param in r.get("parameters", {}):
                    r["parameters"][param] = ov.get("new_value")
                if ov.get("severity"):
                    r["severity"] = ov["severity"]
                r["override"] = {
                    "company": ov.get("company", ""),
                    "parameter": param,
                    "new_value": ov.get("new_value"),
                    "reason": ov.get("reason", ""),
                }
                if ov.get("standard_source"):
                    r["standard_source"] = ov["standard_source"]
        effective.append(r)
    return effective


# 有效规则集 = Baseline（应用 Override）+ 企业自定义规则
EFFECTIVE_RULES = _apply_overrides(BASELINE_RULES)
for _cr in CUSTOM_BASELINE_RULES:
    _c = deepcopy(_cr)
    _c["custom"] = True
    EFFECTIVE_RULES.append(_c)

# 9 项传统检查项 → Baseline 规则 ID 映射（用于"审核标准"勾选联动）
CHECKLIST_TO_RULES = {
    "title_block": ["DOC-001", "DOC-002", "DOC-003", "REV-001", "REV-002"],
    "dimension": ["DIM-001", "DIM-002", "DIM-003", "DIM-004", "DIM-005"],
    "tolerance": ["TOL-001", "TOL-002", "TOL-003", "TOL-004",
                  "GDT-001", "GDT-002", "GDT-003", "GDT-004"],
    "features": ["DOC-004", "DFM-001", "DFM-002", "DFM-003", "DFM-004", "DFM-005"],
    "tech_req": ["MAT-001", "MAT-002", "MAT-003", "MAT-004", "TOL-001"],
    "revision": ["REV-001", "REV-002"],
    "views": [],
    "drafting": [],
    "assembly": [],
}

# 规则大类默认勾选（若勾选任何传统检查项，相关大类全部启用）
def rules_enabled_by_checklist(checklist_ids):
    """根据勾选的传统检查项，返回启用 Baseline 规则 ID 集合"""
    enabled_ids = set()
    for cid in checklist_ids or []:
        for rid in CHECKLIST_TO_RULES.get(cid, []):
            enabled_ids.add(rid)
    return enabled_ids


def get_enabled_rules(checklist_ids):
    """
    返回启用的有效规则列表（应用 Override 后）。
    - Baseline 规则：由传统检查项勾选映射控制
    - 企业自定义规则：enabled=True 即强制启用（企业标准，不随操作员勾选关闭）
    """
    baseline_ids = rules_enabled_by_checklist(checklist_ids)
    enabled = [r for r in EFFECTIVE_RULES if r["id"] in baseline_ids]
    enabled += [r for r in EFFECTIVE_RULES if r.get("custom") and r.get("enabled", True)]
    return enabled


def get_effective_rule(rule_id: str):
    """按 ID 查有效规则（含 Override）"""
    for r in EFFECTIVE_RULES:
        if r["id"] == rule_id:
            return r
    return None


# 数据库
DB_PATH = DATA_DIR / "audit_history.db"

# AI 模型配置（OpenAI 兼容接口，可切换豆包/GPT/Claude）
AI_CONFIG = {
    # 豆包视觉模型（推荐）
    "base_url": os.getenv("AI_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"),
    "api_key": os.getenv("AI_API_KEY", ""),
    "model": os.getenv("AI_MODEL", "doubao-vision-pro-32k"),
    # 备用模型（OpenAI 兼容）
    "fallback_base_url": os.getenv("AI_FALLBACK_BASE_URL", ""),
    "fallback_api_key": os.getenv("AI_FALLBACK_API_KEY", ""),
    "fallback_model": os.getenv("AI_FALLBACK_MODEL", ""),
    "max_retries": 5,
    "timeout": 120,
}

# ── 本地 AI 配置文件（用户在网页界面输入的 Key 保存在这里，绝不提交到 GitHub）──
# 优先级：本地配置文件 > 环境变量 > 默认值
LOCAL_AI_CONFIG_PATH = DATA_DIR / "ai_config.json"

def _load_local_ai_config():
    """从本地配置文件加载 AI 配置（覆盖环境变量的值）"""
    if not LOCAL_AI_CONFIG_PATH.exists():
        return
    try:
        import json
        with open(LOCAL_AI_CONFIG_PATH, "r", encoding="utf-8") as f:
            local = json.load(f)
        for key in ("base_url", "api_key", "model",
                     "fallback_base_url", "fallback_api_key", "fallback_model"):
            if local.get(key):
                AI_CONFIG[key] = local[key]
    except Exception:
        pass  # 配置文件损坏时静默回退到环境变量

def save_ai_config(base_url: str, api_key: str, model: str) -> bool:
    """保存用户在网页界面输入的 AI 配置到本地文件"""
    try:
        import json
        data = {
            "base_url": base_url.strip(),
            "api_key": api_key.strip(),
            "model": model.strip(),
        }
        with open(LOCAL_AI_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        # 立即更新内存中的配置
        AI_CONFIG["base_url"] = data["base_url"]
        AI_CONFIG["api_key"] = data["api_key"]
        AI_CONFIG["model"] = data["model"]
        return True
    except Exception:
        return False

def get_masked_api_key() -> str:
    """返回脱敏后的 API Key（用于前端显示）"""
    key = AI_CONFIG.get("api_key", "")
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return key[:4] + "..." + key[-4:]

# 模块加载时读取本地配置文件
_load_local_ai_config()

# PDF 渲染配置
PDF_CONFIG = {
    "global_dpi": 150,       # 全局缩略图 DPI
    "detail_dpi": 300,       # 局部高清切片 DPI
    "title_block_dpi": 400,  # 标题栏区域 DPI
    "max_detail_chunks": 4,  # 最多切片数量
    "min_chunk_size": 512,   # 切片最小像素
    # ── 资源上限（防止异常/超大/恶意输入导致内存与磁盘峰值）──
    "max_pages": 30,              # 单张 PDF 最多页数
    "max_page_side_pt": 8000,     # 单页最大边长(pt)，A0 约 3370pt，上限 8000pt
    "max_render_pixels": 400_000_000,  # 单次渲染最大像素（超出自动降 DPI）
    "max_total_pixels": 800_000_000,   # 单文件所有切片累计最大像素
}

# 审核并发配置
AUDIT_CONFIG = {
    "max_concurrent_files": 3,    # 同时审核的文件数
    "max_concurrent_chunks": 2,   # 单文件内同时审核的切片数
    "supported_extensions": {".pdf"},
}

# ── 上传限制（防止 DoS：超大小、超量、非 PDF 伪装）──────────
UPLOAD_CONFIG = {
    "max_file_size": 50 * 1024 * 1024,   # 单文件上限 50MB
    "max_files": 10,                     # 单批最多张数
    "chunk_size": 1024 * 1024,           # 分块写入块大小 1MB
    "supported_extensions": {".pdf"},
}

# ── 可选认证与审计日志 ─────────────────────────────────────
# 默认关闭（token 为空 = 不启用鉴权，本地使用不受影响）。
# 生产部署时设置环境变量 AUTH_TOKEN 即可启用 /api/* 的 Bearer Token 鉴权。
AUTH_CONFIG = {
    "token": os.getenv("AUTH_TOKEN", ""),   # 为空 = 关闭
    "audit_log_path": DATA_DIR / "audit.log",
}

# 严重等级定义
SEVERITY_LEVELS = {
    "block":   {"label": "阻断级", "color": "#dc2626", "weight": 100},
    "warning": {"label": "警告级", "color": "#d97706", "weight": 50},
    "info":    {"label": "建议级", "color": "#2563eb", "weight": 10},
}

# 默认审核 Checklist + 自定义检查项合并
DEFAULT_CHECKLIST = [
    {"id": "title_block", "name": "图框与标题栏", "enabled": True,
     "description": "图名、图号、版本、日期、签名、材料、比例、单位是否齐全"},
    {"id": "dimension", "name": "尺寸标注", "enabled": True,
     "description": "缺尺寸、重复尺寸、封闭尺寸链、标注清晰无歧义"},
    {"id": "tolerance", "name": "公差与粗糙度", "enabled": True,
     "description": "尺寸公差、形位公差、表面粗糙度标注完整合理"},
    {"id": "views", "name": "视图表达", "enabled": True,
     "description": "主/俯/侧视图、剖视图、局部放大图充分表达结构"},
    {"id": "features", "name": "工艺特征", "enabled": True,
     "description": "螺纹、孔、倒角、圆角、拔模角标注"},
    {"id": "tech_req", "name": "技术要求", "enabled": True,
     "description": "热处理、表面处理、未注公差等备注齐全"},
    {"id": "drafting", "name": "制图规范", "enabled": True,
     "description": "图层/线型/线宽、字体字号、符号标准(GB/ISO/ANSI)"},
    {"id": "assembly", "name": "装配图专项", "enabled": False,
     "description": "序号/明细表(BOM)、配合代号、焊接符号"},
    {"id": "revision", "name": "版本与变更", "enabled": True,
     "description": "版本号、变更记录栏是否更新"},
]

# 合并自定义检查项（去重，自定义项覆盖默认同名项）
_custom_ids = {c["id"] for c in CUSTOM_CHECKLIST}
DEFAULT_CHECKLIST = [c for c in DEFAULT_CHECKLIST if c["id"] not in _custom_ids]
DEFAULT_CHECKLIST.extend(CUSTOM_CHECKLIST)
