"""
数据模型定义
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from enum import Enum
from datetime import datetime


class Severity(str, Enum):
    BLOCK = "block"
    WARNING = "warning"
    INFO = "info"


class FindingType(str, Enum):
    """Baseline V1.0 发现类型：区分'图纸错误'与'建议优化'"""
    DRAWING_ERROR = "DRAWING_ERROR"
    AMBIGUITY = "AMBIGUITY"
    MANUFACTURING_RISK = "MANUFACTURING_RISK"
    COST_RISK = "COST_RISK"
    INSPECTION_RISK = "INSPECTION_RISK"
    DOCUMENT_CONTROL = "DOCUMENT_CONTROL"


class AuditStatus(str, Enum):
    PENDING = "pending"
    PRECHECKING = "prechecking"
    RENDERING = "rendering"
    AUDITING = "auditing"
    REPORTING = "reporting"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"


class IssueItem(BaseModel):
    """单条审核问题（Baseline V1.0 结构化字段已并入）"""
    id: str = ""
    category: str = ""               # 对应 checklist id / 规则大类
    category_name: str = ""          # 检查项名称
    severity: Severity = Severity.INFO
    title: str = ""                  # 问题简述
    description: str = ""            # 详细描述（finding）
    location: str = ""               # 在图纸中的位置描述（人读）
    suggestion: str = ""             # 修改建议（recommendation）
    page: int = 0                    # 页码（0=全图）
    source: str = "ai"               # rule / ai / deterministic / hybrid

    # ── Baseline V1.0 结构化字段 ─────────────────────────────
    rule_id: str = ""                # 触发的规则 ID（如 DFM-002）
    rule_name: str = ""              # 规则名称
    finding_type: str = ""           # DRAWING_ERROR/AMBIGUITY/...
    result: str = ""                 # PASS/WARNING/CRITICAL/NEEDS_REVIEW/NOT_APPLICABLE
    confidence: float = 1.0          # 置信度 0~1
    evidence: List[str] = Field(default_factory=list)   # 证据列表
    parameters: Dict[str, Any] = Field(default_factory=dict)  # 触发规则参数
    calculation: Dict[str, Any] = Field(default_factory=dict)  # 计算过程 {formula, value, ...}
    engineering_risk: str = ""       # 工程风险
    standard_source: str = "BASELINE"  # 规则来源（BASELINE/企业标准）
    requires_human_review: bool = False  # 是否需要人工复核
    location_view: str = ""          # 视图/剖视/局部放大图
    location_feature: str = ""       # 特征标识


class CheckResult(BaseModel):
    """单个检查项的结果"""
    checklist_id: str
    checklist_name: str
    passed: bool = True
    issues: List[IssueItem] = Field(default_factory=list)
    note: str = ""


class FileAuditResult(BaseModel):
    """单张图纸的审核结果"""
    file_path: str
    file_name: str
    page_count: int = 0
    status: AuditStatus = AuditStatus.PENDING
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration_seconds: float = 0.0

    # 规则前置检查结果
    precheck_passed: bool = True
    precheck_issues: List[IssueItem] = Field(default_factory=list)
    extracted_text: str = ""          # 提取的矢量文本
    title_block_text: str = ""        # 标题栏区域限定文本（坐标过滤，用于降低规则误报）
    title_block_info: Dict[str, Any] = Field(default_factory=dict)

    # Baseline V1.0：确定性规则计算结果（DFM-001/002、GDT-001 等）
    deterministic_issues: List[IssueItem] = Field(default_factory=list)

    # Baseline V1.0：本次审核启用的规则
    enabled_rules: List[Dict[str, Any]] = Field(default_factory=list)
    audit_standard: str = "Baseline V1.0"
    # 持久化元信息（重启后用于完整恢复审核详情）
    rules_version: str = "Baseline V1.0"   # 规则集版本
    model_version: str = ""                # AI 模型版本
    error: str = ""                        # 失败时的错误信息

    # AI 审核结果
    check_results: List[CheckResult] = Field(default_factory=list)
    ai_issues: List[IssueItem] = Field(default_factory=list)

    # 汇总
    total_issues: int = 0
    block_count: int = 0
    warning_count: int = 0
    info_count: int = 0
    passed: bool = True
    overall_comment: str = ""

    # 产物路径
    report_md_path: str = ""
    report_json_path: str = ""

    # 渲染图片（base64 缩略图，用于前端展示）
    thumbnail: str = ""


class BatchAuditResult(BaseModel):
    """批量审核任务结果"""
    task_id: str
    folder_path: str
    folder_name: str
    status: AuditStatus = AuditStatus.PENDING
    created_at: str = ""
    completed_at: Optional[str] = None
    total_files: int = 0
    completed_files: int = 0
    failed_files: int = 0

    files: List[FileAuditResult] = Field(default_factory=list)

    # 汇总统计
    total_issues: int = 0
    block_count: int = 0
    warning_count: int = 0
    info_count: int = 0
    pass_rate: float = 0.0

    summary_report_path: str = ""

    # 持久化元信息（重启后用于完整恢复）
    audit_standard: str = "Baseline V1.0"
    model_version: str = ""
    rules_version: str = "Baseline V1.0"
    error: str = ""


class TaskCreateRequest(BaseModel):
    """创建审核任务请求"""
    folder_path: str
    checklist_ids: Optional[List[str]] = None   # 为空则使用全部启用项
    recursive: bool = True
