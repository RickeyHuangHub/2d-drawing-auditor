"""
============================================================
  DRAWING AUDIT EXPERT — BASELINE RULES V1.0
  ============================================================
  本文件是 AI 审图系统的"输入系统规则"核心数据层。
  28 条 Baseline 规则以结构化数据定义，供：
    - rule_engine.py   （确定性规则：程序执行）
    - ai_auditor.py    （Hybrid / AI 规则：注入视觉大模型逐条执行）
    - 前端规则库展示     （/api/rules）
  统一消费。

  设计约束（用户指定）：
    1. 规则写成 AI 可以逐条执行、必须给证据、不能乱猜的审核标准。
    2. 企业不得直接修改这 28 条 Baseline，只能通过 custom_rules.py
       的 CUSTOM_OVERRIDES（覆盖参数/严重度）与
       CUSTOM_BASELINE_RULES（新增企业自定义规则）扩展。
    3. 优先级：Project > Customer > Company > Baseline。
    4. 不要静默改变 severity / threshold 值。
============================================================
"""

# ── 允许的结果值 ─────────────────────────────────────────────
ALLOWED_RESULTS = ("PASS", "WARNING", "CRITICAL", "NEEDS_REVIEW", "NOT_APPLICABLE")

# ── finding_type 枚举（用户指定，用于报告区分"图纸错误"与"建议优化"） ──
FINDING_TYPES = (
    "DRAWING_ERROR",      # 图纸本身有错：矛盾、缺失、错误标注
    "AMBIGUITY",          # 图纸信息不明确、可多解，需人工确认
    "MANUFACTURING_RISK", # 可制造性风险：工艺难做、加工困难
    "COST_RISK",          # 成本风险：过严公差等带来成本/工艺代价
    "INSPECTION_RISK",    # 检测/检验困难或歧义
    "DOCUMENT_CONTROL",   # 文件控制：图号/版本/材料/修订等文档类问题
)

FINDING_TYPE_LABEL_ZH = {
    "DRAWING_ERROR": "图纸错误",
    "AMBIGUITY": "信息歧义",
    "MANUFACTURING_RISK": "可制造性风险",
    "COST_RISK": "成本风险",
    "INSPECTION_RISK": "检测风险",
    "DOCUMENT_CONTROL": "文件控制",
}

# ── 严重度映射（Baseline 的 CRITICAL/WARNING → 系统 block/warning/info） ──
SEVERITY_MAP = {
    "CRITICAL": "block",
    "WARNING": "warning",
    "INFO": "info",
    "NEEDS_REVIEW": "warning",
}

# ── 全局审核原则（System/Baseline Instruction）─────────────────
BASELINE_INSTRUCTION = """DRAWING AUDIT EXPERT — BASELINE V1.0
ROLE: You are an engineering drawing audit assistant. Audit the supplied 2D mechanical drawing against the enabled Baseline Rules.

CORE PRINCIPLES:
1. Review only information visible or reliably extracted from the drawing.
2. Never invent dimensions, tolerances, materials, datums, notes, processes,
   standards, revisions, or design intent.
3. Every CRITICAL or WARNING finding must contain verifiable drawing evidence.
4. If evidence is insufficient, return NEEDS_REVIEW instead of guessing.
5. Distinguish drawing errors from manufacturability risks.
6. Do not report a rule when it is not applicable to the drawing.
7. Consider relationships between views, sections, details, notes,
   dimensions, tolerances, GD&T, material and manufacturing requirements.
8. Where company/customer/project standards override Baseline parameters,
   apply the highest-priority active rule.
9. Rule priority: Project > Customer > Company > Baseline.
10. Do not silently change severity or threshold values.

ALLOWED RESULTS: PASS WARNING CRITICAL NEEDS_REVIEW NOT_APPLICABLE

EVIDENCE POLICY: No Evidence → No Finding.
For every finding identify, where possible:
- Drawing/Page - View/Section/Detail - Feature - Existing drawing value/text
- Triggered rule - Calculated value, if applicable - Reason
- Recommended engineering review/action

Do not claim a drawing is fully compliant merely because no issue was detected."""


# ── 28 条 Baseline 规则 ───────────────────────────────────────
# 字段说明：
#   id           唯一规则 ID（如 DOC-001）
#   name         规则英文名（Baseline 原名）
#   name_zh      规则中文名（前端/报告展示）
#   category     规则大类（DOC/DIM/TOL/GDT/MAT/DFM/REV）
#   category_name 大类中文名
#   severity     Baseline 定义的严重度（CRITICAL / WARNING）
#   execution    Deterministic（程序可算）/ Hybrid（规则+AI）/ AI（AI 综合）
#   finding_type 默认发现类型（见 FINDING_TYPES）
#   condition    触发/判断条件（供人阅读）
#   prompt       AI 可逐条执行的审核指令
#   parameters   可被企业 Override 的参数（threshold 等）
#   enabled      是否默认启用
#   standard_source 规则来源（BASELINE / 企业标准）
BASELINE_RULES = [
    # ════════════ A. 图纸完整性 — DOC ════════════
    {
        "id": "DOC-001",
        "name": "Drawing / Part Number Missing",
        "name_zh": "缺少图号/零件号",
        "category": "DOC",
        "category_name": "图纸完整性",
        "severity": "CRITICAL",
        "execution": "Deterministic",
        "finding_type": "DOCUMENT_CONTROL",
        "condition": "图纸没有可以唯一识别零件/图纸的 Drawing No. / Part No.",
        "prompt": (
            "Inspect the title block and document identification area. "
            "Verify that a unique Drawing Number or Part Number is present and readable. "
            "Do not treat filename alone as sufficient drawing identification. "
            "If absent or unreadable: CRITICAL. "
            "If the title block cannot be reliably read: NEEDS_REVIEW."
        ),
        "parameters": {},
        "enabled": True,
        "standard_source": "BASELINE",
    },
    {
        "id": "DOC-002",
        "name": "Essential Title Block Information Missing",
        "name_zh": "标题栏关键信息缺失",
        "category": "DOC",
        "category_name": "图纸完整性",
        "severity": "WARNING",
        "execution": "Hybrid",
        "finding_type": "DOCUMENT_CONTROL",
        "condition": "Part/Drawing Name、Scale、Units、Sheet number（多页）、Projection method（适用时）缺失。",
        "prompt": (
            "Check whether essential title-block information required to correctly "
            "interpret the drawing is present. Report only missing information that "
            "materially affects interpretation, manufacturing or inspection. "
            "Do not flag fields that are clearly not applicable."
        ),
        "parameters": {},
        "enabled": True,
        "standard_source": "BASELINE",
    },
    {
        "id": "DOC-003",
        "name": "Material Specification Missing",
        "name_zh": "缺少材料规格",
        "category": "DOC",
        "category_name": "图纸完整性",
        "severity": "CRITICAL",
        "execution": "Hybrid",
        "finding_type": "DOCUMENT_CONTROL",
        "condition": "零件明显需要材料定义，但标题栏、Notes、BOM 等均没有材料要求。",
        "prompt": (
            "Determine whether the manufactured part requires a material specification. "
            "Search title block, general notes, BOM and referenced specifications. "
            "If no material can be reliably established: CRITICAL. "
            "If material may be defined through an external referenced document but "
            "cannot be verified: NEEDS_REVIEW."
        ),
        "parameters": {},
        "enabled": True,
        "standard_source": "BASELINE",
    },
    {
        "id": "DOC-004",
        "name": "Undefined Manufacturing Feature",
        "name_zh": "制造特征定义不完整",
        "category": "DOC",
        "category_name": "图纸完整性",
        "severity": "CRITICAL",
        "execution": "AI",
        "finding_type": "AMBIGUITY",
        "condition": "孔、槽、台阶、倒角等存在，但信息不足以唯一制造。",
        "prompt": (
            "Identify manufacturing features that cannot be uniquely interpreted from "
            "the drawing. Check geometry, dimensions, views, sections, details and notes "
            "together. Do not infer hidden design intent. If two competent manufacturers "
            "could reasonably interpret the feature differently, report the ambiguity."
        ),
        "parameters": {},
        "enabled": True,
        "standard_source": "BASELINE",
    },

    # ════════════ B. 尺寸 — DIM ════════════
    {
        "id": "DIM-001",
        "name": "Incomplete Feature Dimension",
        "name_zh": "特征尺寸不完整",
        "category": "DIM",
        "category_name": "尺寸",
        "severity": "CRITICAL",
        "execution": "Hybrid",
        "finding_type": "DRAWING_ERROR",
        "condition": "孔、槽、螺纹、台阶、沉孔、沉头孔、倒角等不具备制造需要的信息。",
        "prompt": (
            "For each manufacturing feature, determine whether sufficient dimensions "
            "exist to manufacture it. Depending on feature type, verify: size, position, "
            "quantity, depth, thread specification, counterbore/countersink information, "
            "radius/chamfer information. Do not require parameters that are irrelevant "
            "to the feature."
        ),
        "parameters": {},
        "enabled": True,
        "standard_source": "BASELINE",
    },
    {
        "id": "DIM-002",
        "name": "Feature Position Not Fully Defined",
        "name_zh": "特征位置未完全定义",
        "category": "DIM",
        "category_name": "尺寸",
        "severity": "CRITICAL",
        "execution": "Hybrid",
        "finding_type": "AMBIGUITY",
        "condition": "制造关键特征相对已定义几何/基准的位置信息不足。",
        "prompt": (
            "Verify that manufacturing-critical features are uniquely located relative "
            "to defined geometry or datums. A feature must not be considered fully located "
            "merely because its size is defined. If X/Y, radial, angular, pattern or "
            "equivalent positioning information is insufficient: CRITICAL."
        ),
        "parameters": {},
        "enabled": True,
        "standard_source": "BASELINE",
    },
    {
        "id": "DIM-003",
        "name": "Duplicate / Closed Dimension Chain",
        "name_zh": "重复/封闭尺寸链",
        "category": "DIM",
        "category_name": "尺寸",
        "severity": "WARNING",
        "execution": "Hybrid",
        "finding_type": "DRAWING_ERROR",
        "condition": "存在冗余或封闭尺寸链（如 A-B=30 B-C=20 A-C=50），可能过度约束制造解读。",
        "prompt": (
            "Detect redundant or closed dimension chains that may over-constrain "
            "manufacturing interpretation. Distinguish reference dimensions from "
            "controlling dimensions. Do not flag dimensions explicitly identified "
            "as REF/reference."
        ),
        "parameters": {},
        "enabled": True,
        "standard_source": "BASELINE",
    },
    {
        "id": "DIM-004",
        "name": "Cross-View Dimension or Feature Conflict",
        "name_zh": "跨视图尺寸/特征冲突",
        "category": "DIM",
        "category_name": "尺寸",
        "severity": "CRITICAL",
        "execution": "Hybrid",
        "finding_type": "DRAWING_ERROR",
        "condition": "不同视图/剖视/局部放大图中特征数量、尺寸值、孔径、螺纹、位置、几何、深度、阵列定义相互矛盾。",
        "prompt": (
            "Compare all relevant views, sections and detail views. Detect contradictions "
            "in: feature quantity, dimension value, hole size, thread specification, "
            "feature position, geometry, depth, pattern definition. Report BOTH "
            "conflicting pieces of evidence, e.g.: Front View: 4×Ø6 Detail A: 6×Ø6 "
            "→ Conflict detected."
        ),
        "parameters": {},
        "enabled": True,
        "standard_source": "BASELINE",
    },
    {
        "id": "DIM-005",
        "name": "Dimension-to-Geometry Mismatch",
        "name_zh": "尺寸与几何不匹配",
        "category": "DIM",
        "category_name": "尺寸",
        "severity": "CRITICAL",
        "execution": "AI",
        "finding_type": "DRAWING_ERROR",
        "condition": "尺寸文本/引线/箭头与所标注的几何特征不一致。",
        "prompt": (
            "Check whether dimension text, leaders, arrows and associated geometry appear "
            "to describe the same feature. Detect obvious cases where a dimension or "
            "callout points to incompatible geometry. Do not flag uncertain leader "
            "associations as errors. Use NEEDS_REVIEW when association cannot be "
            "established reliably."
        ),
        "parameters": {},
        "enabled": True,
        "standard_source": "BASELINE",
    },

    # ════════════ C. 公差 — TOL ════════════
    {
        "id": "TOL-001",
        "name": "General Tolerance Undefined",
        "name_zh": "未注公差未定义",
        "category": "TOL",
        "category_name": "公差",
        "severity": "WARNING",
        "execution": "Hybrid",
        "finding_type": "DRAWING_ERROR",
        "condition": "存在未单独标注公差的制造尺寸，且无法确定适用的未注公差规范。",
        "prompt": (
            "Determine whether dimensions without individual tolerances are governed by "
            "a general tolerance specification. Search title block and general notes. "
            "If un-toleranced manufacturing dimensions exist and no applicable general "
            "tolerance can be established: WARNING."
        ),
        "parameters": {},
        "enabled": True,
        "standard_source": "BASELINE",
    },
    {
        "id": "TOL-002",
        "name": "Suspected Functional Dimension Tolerance Too Loose",
        "name_zh": "疑似功能尺寸公差过松",
        "category": "TOL",
        "category_name": "公差",
        "severity": "WARNING",
        "execution": "AI",
        "finding_type": "AMBIGUITY",
        "condition": "与配合、轴承、定位、密封、对中功能相关的尺寸公差相对功能而言过松。",
        "prompt": (
            "Identify dimensions that appear associated with mating, bearing, locating, "
            "sealing or alignment functions. Evaluate whether the stated tolerance "
            "appears unusually loose for the apparent function. Do not invent required "
            "tolerance values. If functional intent is uncertain: NEEDS_REVIEW."
        ),
        "parameters": {},
        "enabled": True,
        "standard_source": "BASELINE",
    },
    {
        "id": "TOL-003",
        "name": "Excessively Tight Tolerance / Cost Risk",
        "name_zh": "公差过严/成本风险",
        "category": "TOL",
        "category_name": "公差",
        "severity": "WARNING",
        "execution": "Hybrid",
        "finding_type": "COST_RISK",
        "condition": "相对特征尺寸、工艺与周边要求而言公差过严，存在可制造性/成本顾虑。",
        "prompt": (
            "Identify unusually tight dimensional tolerances relative to feature size, "
            "manufacturing process and surrounding requirements. Flag only when there is "
            "a credible manufacturing/cost concern. Explain why the tolerance deserves "
            "engineering review. Do not automatically assume tight tolerance is incorrect. "
            "IMPORTANT: this finding type is Cost / Manufacturability Risk, NOT a drawing error."
        ),
        "parameters": {},
        "enabled": True,
        "standard_source": "BASELINE",
    },
    {
        "id": "TOL-004",
        "name": "Conflicting Tolerance Requirements",
        "name_zh": "公差要求冲突",
        "category": "TOL",
        "category_name": "公差",
        "severity": "CRITICAL",
        "execution": "Hybrid",
        "finding_type": "DRAWING_ERROR",
        "condition": "单个尺寸公差、未注公差、极限尺寸、配合代号、Notes、尺寸链、引用要求之间相互冲突。",
        "prompt": (
            "Detect conflicting tolerance requirements between: individual dimension "
            "tolerances, general tolerances, limit dimensions, fit specifications, notes, "
            "dimension chains, referenced requirements. Provide BOTH conflicting "
            "requirements as evidence."
        ),
        "parameters": {},
        "enabled": True,
        "standard_source": "BASELINE",
    },

    # ════════════ D. GD&T ════════════
    {
        "id": "GDT-001",
        "name": "Referenced Datum Does Not Exist",
        "name_zh": "被引用基准不存在",
        "category": "GDT",
        "category_name": "形位公差",
        "severity": "CRITICAL",
        "execution": "Deterministic",
        "finding_type": "DRAWING_ERROR",
        "condition": "特征控制框引用的基准（如 POSITION | Ø0.10 | A | B | C）在图纸上未定义。",
        "prompt": (
            "Extract all datum references used by feature control frames. Verify that "
            "every referenced datum exists and is clearly defined on the drawing. "
            "Example: POSITION | Ø0.10 | A | B | C requires valid datum features A, B "
            "and C. Missing referenced datum → CRITICAL."
        ),
        "parameters": {},
        "enabled": True,
        "standard_source": "BASELINE",
    },
    {
        "id": "GDT-002",
        "name": "Datum Definition Ambiguous",
        "name_zh": "基准定义歧义",
        "category": "GDT",
        "category_name": "形位公差",
        "severity": "CRITICAL",
        "execution": "Hybrid",
        "finding_type": "AMBIGUITY",
        "condition": "基准符号与目标基准特征关联不清晰，存在歧义/重复/分离。",
        "prompt": (
            "Verify that each datum symbol is clearly associated with the intended datum "
            "feature. Flag ambiguous, duplicated, detached or otherwise unclear datum "
            "definitions that could change inspection interpretation."
        ),
        "parameters": {},
        "enabled": True,
        "standard_source": "BASELINE",
    },
    {
        "id": "GDT-003",
        "name": "Invalid / Incomplete Feature Control Frame",
        "name_zh": "特征控制框无效/不完整",
        "category": "GDT",
        "category_name": "形位公差",
        "severity": "CRITICAL",
        "execution": "Hybrid",
        "finding_type": "DRAWING_ERROR",
        "condition": "特征控制框缺少几何特征、公差值、Ø 修饰符、基准引用、材料条件修饰符等要素。",
        "prompt": (
            "Check feature control frames for structural completeness and internal "
            "consistency: Geometric characteristic, Tolerance value, Ø modifier where "
            "required, Datum references, Material condition modifiers. Do not invent "
            "missing GD&T elements. Report the exact frame as evidence whenever possible."
        ),
        "parameters": {},
        "enabled": True,
        "standard_source": "BASELINE",
    },
    {
        "id": "GDT-004",
        "name": "GD&T / Basic Dimension / Datum Scheme Inconsistency",
        "name_zh": "GD&T/基本尺寸/基准体系不一致",
        "category": "GDT",
        "category_name": "形位公差",
        "severity": "CRITICAL",
        "execution": "Hybrid",
        "finding_type": "DRAWING_ERROR",
        "condition": "位置度/方向控制缺少支撑基本尺寸与基准引用，或与基准体系明显矛盾。",
        "prompt": (
            "Evaluate whether position/orientation controls have sufficient supporting "
            "basic dimensions and datum references. Detect obvious contradictions between "
            "basic dimensions, feature control frames and datum structure. If full GD&T "
            "intent cannot be determined: NEEDS_REVIEW."
        ),
        "parameters": {},
        "enabled": True,
        "standard_source": "BASELINE",
    },

    # ════════════ E. 材料 / 工艺 — MAT ════════════
    {
        "id": "MAT-001",
        "name": "Material Specification Ambiguous",
        "name_zh": "材料规格歧义",
        "category": "MAT",
        "category_name": "材料/工艺",
        "severity": "CRITICAL",
        "execution": "Hybrid",
        "finding_type": "AMBIGUITY",
        "condition": "已写材料但材料牌号无法唯一确定（与 DOC-003「无材料」区分）。",
        "prompt": (
            "Verify that the material designation is sufficiently specific for "
            "procurement and manufacturing. Flag ambiguous, incomplete or internally "
            "inconsistent material designations. Do not guess equivalent material grades. "
            "NOTE: differs from DOC-003 — DOC-003 = no material; MAT-001 = material "
            "written but cannot be uniquely determined."
        ),
        "parameters": {},
        "enabled": True,
        "standard_source": "BASELINE",
    },
    {
        "id": "MAT-002",
        "name": "Material / Surface Treatment Incompatibility",
        "name_zh": "材料与表面处理不兼容",
        "category": "MAT",
        "category_name": "材料/工艺",
        "severity": "CRITICAL",
        "execution": "Hybrid",
        "finding_type": "DRAWING_ERROR",
        "condition": "如 SUS304 + Black Anodize（黑色阳极氧化）等材料与表面处理在技术上不兼容或高度可疑。",
        "prompt": (
            "Check compatibility between specified base material and surface "
            "treatment/coating. Report combinations that are technically incompatible or "
            "highly suspect. When compatibility depends on a special process not defined "
            "on the drawing: NEEDS_REVIEW."
        ),
        "parameters": {},
        "enabled": True,
        "standard_source": "BASELINE",
    },
    {
        "id": "MAT-003",
        "name": "Material / Heat Treatment / Hardness Conflict",
        "name_zh": "材料/热处理/硬度冲突",
        "category": "MAT",
        "category_name": "材料/工艺",
        "severity": "CRITICAL",
        "execution": "Hybrid",
        "finding_type": "DRAWING_ERROR",
        "condition": "如 AL6061-T6 + HRC58-62 等材料牌号、状态、热处理与硬度要求互不兼容。",
        "prompt": (
            "Check whether material grade, material condition, heat treatment and "
            "hardness requirements are mutually compatible. Report physically or "
            "technically inconsistent combinations. Provide ALL conflicting "
            "specifications as evidence."
        ),
        "parameters": {},
        "enabled": True,
        "standard_source": "BASELINE",
    },
    {
        "id": "MAT-004",
        "name": "Surface Finish / Treatment Area Ambiguous",
        "name_zh": "表面粗糙度/处理区域歧义",
        "category": "MAT",
        "category_name": "材料/工艺",
        "severity": "WARNING",
        "execution": "AI",
        "finding_type": "AMBIGUITY",
        "condition": "表面粗糙度、镀层、阳极氧化、喷涂等要求未明确适用表面，可能影响制造。",
        "prompt": (
            "Determine whether surface roughness, coating, plating, anodizing, painting "
            "or other surface requirements clearly define the applicable surfaces. If the "
            "requirement could reasonably apply to different surfaces and materially "
            "affect manufacturing: WARNING."
        ),
        "parameters": {},
        "enabled": True,
        "standard_source": "BASELINE",
    },

    # ════════════ F. DFM — 可制造性 ════════════
    {
        "id": "DFM-001",
        "name": "Hole Edge Distance Risk",
        "name_zh": "孔边距风险",
        "category": "DFM",
        "category_name": "可制造性",
        "severity": "WARNING",
        "execution": "Deterministic",
        "finding_type": "MANUFACTURING_RISK",
        "condition": "孔边到零件边缘的最小距离 E 与孔径 D 之比 E/D 低于阈值（默认 1.0）。",
        "prompt": (
            "Calculate minimum edge distance when geometry permits reliable measurement. "
            "If E / D < minimum_edge_distance_ratio → WARNING. Report E, D and calculated "
            "ratio. Do not estimate dimensions from drawing scale when actual "
            "geometry/dimensions are unavailable."
        ),
        "parameters": {"minimum_edge_distance_ratio": 1.0},
        "enabled": True,
        "standard_source": "BASELINE",
    },
    {
        "id": "DFM-002",
        "name": "Deep Hole Risk",
        "name_zh": "深孔风险",
        "category": "DFM",
        "category_name": "可制造性",
        "severity": "WARNING",
        "execution": "Deterministic",
        "finding_type": "MANUFACTURING_RISK",
        "condition": "钻孔深径比 L/D 超过阈值（默认 5.0）。",
        "prompt": (
            "For applicable drilled holes calculate depth-to-diameter ratio. If "
            "L / D > maximum_hole_depth_ratio → WARNING. Report: Diameter, Depth, L/D. "
            "Do not apply blindly to features produced by clearly specified alternative "
            "manufacturing processes."
        ),
        "parameters": {"maximum_hole_depth_ratio": 5.0},
        "enabled": True,
        "standard_source": "BASELINE",
    },
    {
        "id": "DFM-003",
        "name": "Internal Corner / Tool Access Risk",
        "name_zh": "内角/刀具可达性风险",
        "category": "DFM",
        "category_name": "可制造性",
        "severity": "WARNING",
        "execution": "Hybrid",
        "finding_type": "MANUFACTURING_RISK",
        "condition": "内角、凹槽、型腔按所标注工艺难以或无法加工（考虑刀具半径与可达性）。",
        "prompt": (
            "Identify internal corners, pockets or radii that may be difficult or "
            "impossible to produce using the apparent machining process. Consider tool "
            "radius and tool access. Do not assume CNC milling if another manufacturing "
            "process is explicitly specified."
        ),
        "parameters": {},
        "enabled": True,
        "standard_source": "BASELINE",
    },
    {
        "id": "DFM-004",
        "name": "Thin Wall / Narrow Slot / Small Feature Risk",
        "name_zh": "薄壁/窄槽/微小特征风险",
        "category": "DFM",
        "category_name": "可制造性",
        "severity": "WARNING",
        "execution": "Hybrid",
        "finding_type": "MANUFACTURING_RISK",
        "condition": "薄壁、窄槽、微小特征可能带来加工、变形、工装或检测风险（阈值随材料/工艺/企业标准而定）。",
        "prompt": (
            "Identify thin walls, narrow slots and unusually small features that may "
            "create machining, deformation, tooling or inspection risk. Apply configured "
            "process/material thresholds when available. Without reliable thresholds: "
            "NEEDS_REVIEW rather than declaring the design invalid."
        ),
        "parameters": {
            "minimum_wall_thickness": None,
            "minimum_slot_width": None,
            "minimum_feature_size": None,
        },
        "enabled": True,
        "standard_source": "BASELINE",
    },
    {
        "id": "DFM-005",
        "name": "Combined Manufacturing Risk",
        "name_zh": "综合制造风险",
        "category": "DFM",
        "category_name": "可制造性",
        "severity": "WARNING",
        "execution": "AI",
        "finding_type": "MANUFACTURING_RISK",
        "condition": "单项可接受，但特征尺寸/深径比/材料/公差/GD&T/粗糙度/热处理/表面处理/刀具可达性组合后制造难度显著上升。",
        "prompt": (
            "Evaluate combinations of requirements that may individually appear "
            "acceptable but collectively create significant manufacturing difficulty. "
            "Consider together: feature size, aspect ratio, material, tolerance, GD&T, "
            "surface roughness, heat treatment, surface treatment, tool accessibility. "
            "Do not duplicate findings already fully explained by another rule. Use this "
            "rule for COMBINED manufacturing risk. Example: Ø3 × 30 deep hole SUS304 "
            "±0.02 Ra0.8 — each single item may not be absolutely wrong, but combined "
            "risk clearly rises."
        ),
        "parameters": {},
        "enabled": True,
        "standard_source": "BASELINE",
    },

    # ════════════ G. 版本 / 文件控制 — REV ════════════
    {
        "id": "REV-001",
        "name": "Revision Missing / Invalid",
        "name_zh": "版本号缺失/无效",
        "category": "REV",
        "category_name": "版本/文件控制",
        "severity": "CRITICAL",
        "execution": "Deterministic",
        "finding_type": "DOCUMENT_CONTROL",
        "condition": "需要版本控制时，图纸缺少可读的当前版本标识。",
        "prompt": (
            "Verify that the drawing contains a readable current revision identifier "
            "where revision control is required. Check title block and revision area. "
            "Missing, unreadable or structurally invalid revision information: CRITICAL "
            "or NEEDS_REVIEW depending on evidence."
        ),
        "parameters": {},
        "enabled": True,
        "standard_source": "BASELINE",
    },
    {
        "id": "REV-002",
        "name": "Revision Table / Current Revision Conflict",
        "name_zh": "修订表与当前版本冲突",
        "category": "REV",
        "category_name": "版本/文件控制",
        "severity": "CRITICAL",
        "execution": "Hybrid",
        "finding_type": "DOCUMENT_CONTROL",
        "condition": "标题栏当前版本与修订历史最新条目冲突（版本号/日期/描述/审批）。",
        "prompt": (
            "Compare the current revision shown in the title block with the latest "
            "applicable entry in the revision history. Check: Revision ID, Date, "
            "Description, Approval information where applicable. If revision identifiers "
            "conflict: CRITICAL. Show BOTH values as evidence."
        ),
        "parameters": {},
        "enabled": True,
        "standard_source": "BASELINE",
    },
]

# ── 大类定义（用于前端规则库分组展示） ───────────────────────
RULE_CATEGORIES = [
    {"id": "DOC", "name": "图纸完整性", "icon": "📄", "desc": "图号、标题栏、材料、制造特征完整性"},
    {"id": "DIM", "name": "尺寸", "icon": "📏", "desc": "特征尺寸、位置、封闭链、跨视图冲突、尺寸与几何匹配"},
    {"id": "TOL", "name": "公差", "icon": "🎯", "desc": "未注公差、功能公差、成本风险、公差冲突"},
    {"id": "GDT", "name": "形位公差", "icon": "🔧", "desc": "基准存在性、基准定义、特征控制框、GD&T 体系一致性"},
    {"id": "MAT", "name": "材料/工艺", "icon": "🧪", "desc": "材料歧义、材料与表面处理/热处理兼容性"},
    {"id": "DFM", "name": "可制造性", "icon": "🏭", "desc": "孔边距、深孔、刀具可达性、薄壁窄槽、综合制造风险"},
    {"id": "REV", "name": "版本/文件控制", "icon": "📋", "desc": "版本缺失/无效、修订表与当前版本冲突"},
]

# ── 查询辅助函数 ─────────────────────────────────────────────

def get_rule(rule_id: str):
    """按 ID 查规则"""
    for r in BASELINE_RULES:
        if r["id"] == rule_id:
            return r
    return None


def rules_by_category(category: str):
    """按大类取规则"""
    return [r for r in BASELINE_RULES if r["category"] == category]


def get_rules_by_execution(execution: str):
    """按执行方式取规则（Deterministic / Hybrid / AI）"""
    return [r for r in BASELINE_RULES if r["execution"] == execution]


def count_rules() -> int:
    return len(BASELINE_RULES)
