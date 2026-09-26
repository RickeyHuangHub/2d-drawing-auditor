"""
============================================================
  自定义审图规则与技术要求配置（LeRouge 定制版）
  ============================================================
  这是你添加自定义规则的唯一入口。修改后重启服务即可生效。

  六个区域：
  1. CUSTOM_CHECKLIST       — 自定义 AI 检查项（需要 AI 看图纸判断的）
  2. CUSTOM_TECH_REQS       — 自定义技术要求（注入 AI 提示词作为审核依据）
  3. CUSTOM_RULE_CHECKS     — 自定义规则检查（正则匹配 PDF 文本，零误差）
  4. CUSTOM_OVERRIDES       — Baseline 参数/严重度覆盖（企业标准优先于 Baseline）
  5. CUSTOM_BASELINE_RULES  — 企业自定义规则（追加到 28 条 Baseline 之后）
  6. CUSTOM_TITLE_BLOCK_FIELDS — 标题栏字段名映射

  双 Profile 架构（AiWorkLab 规则母库）：
  - Profile A = LeRouge（现场实战/保守型）：聚焦 8 条核心红线 + 免检降噪 + 需人工审核
  - Profile B = 标准全功能（高校教学/终审型）：全量 28 条母库 + 补充规则 + 严格判定
  每条 CUSTOM_BASELINE_RULES 通过 "profile" 字段标记归属：
    "A"  = 仅 Profile A 启用
    "B"  = 仅 Profile B 启用（补充母库缺口）
    "AB" = 两个 Profile 均启用

  规则优先级：Project > Customer > Company > Baseline。
  企业不应直接修改 baseline_rules.py，应通过 4/5 两个区域扩展。
============================================================
"""

# ============================================================
# 1. 自定义 AI 检查项
# ============================================================
# 每条检查项会作为独立条目出现在前端"审核标准"弹窗中，
# 并作为 prompt 传给 AI 视觉模型逐项审查。
# （LeRouge 定制采用 CUSTOM_BASELINE_RULES 完整规则形态，本区域保持空置）

CUSTOM_CHECKLIST = []


# ============================================================
# 2. 自定义技术要求（注入 AI 提示词）
# ============================================================
# 这里写的内容会作为"审核依据"附加在 AI 系统提示词中。
# 适合放：行业标准条款、公司工艺规范、材料特殊要求、审查范围边界等。
# 每条可用 "profile" 字段标记归属：A / B / AB（缺省视为 AB）。
# Profile A（LeRouge）注入审查范围边界、公差表豁免与零件映射；
# Profile B（标准全功能）不注入 LeRouge 专属上下文。
# ============================================================

CUSTOM_TECH_REQS = [
    {
        "profile": "A",
        "text": "【审查范围】图框（标题栏）与左下角注释内容不纳入AI审查；"
                "审查对象为视图区图形、尺寸、符号及技术要求文字。"
                "版本信息（Revision）、签审流程（Reviewer/Approver）、"
                "模板通用公差表为免检项，不报错、不阻断，转人工线下确认。",
    },
    {
        "profile": "A",
        "text": "【公差表豁免】图纸模板自带的未注线性/角度公差小表与 GB/T 1804-m "
                "的文字冲突属模板遗留问题，AI 忽略；配合尺寸一律以主视图标注为准。",
    },
    {
        "profile": "A",
        "text": "【零件映射】本批零件及审查重点：大板GZ-020-0101a（孔位尺寸链/螺纹/位置度）；"
                "缓存垫GZ-020-0209（内腔剖视/材质表处/形位公差）；"
                "轴承盖GZ-020-0363（轴承位公差/粗糙度/形位公差/基准）；"
                "机架模块GZ-020-0001a（焊接符号/折弯R/压铆/展开干涉）；"
                "光电挡板GZ-020-0128（传感器安装孔位/位置度/孔距匹配）；"
                "插座板GZ-020-0351a（薄壁加强/安装孔/毛刺）；"
                "轴承座GZ-020-0117、丝杆座GZ-020-0119（同轴度/配合公差/防锈）；"
                "滑块GZ-020-0104、升降尾板GZ-020-0106（封闭尺寸链/双导向孔平行度）；"
                "导向轴GZ-020-0105、惰轮轴GZ-020-0116（直线度/圆柱度/越程槽/表面处理）；"
                "光电支架GZ-020-0126（孔距链/折弯内角R/镀锌）；"
                "电机座GZ-020-0208（法兰孔距折弯线拉料/电机止口标注）；"
                "GZ-020-0005（机加件，6061铝合金细砂光亮阳极）。",
    },
]


# ============================================================
# 3. 自定义规则检查（正则匹配 PDF 矢量文本）
# ============================================================
# 对于可以用文字匹配精确判断的规则，在这里定义正则表达式。
# 系统会从 PDF 中提取矢量文本，用这些正则检查。
# 比 AI 判断更准确、零成本、不会漏。
# （LeRouge 定制暂未启用正则规则，如需启用取消注释即可）

CUSTOM_RULE_CHECKS = []


# ============================================================
# 4. 自定义标题栏字段映射（可选）
# ============================================================
# 如果你们公司的标题栏字段名与默认不同，在这里映射。
# 系统会用这些标签去提取标题栏信息。
# ============================================================

CUSTOM_TITLE_BLOCK_FIELDS = {
    # "drawing_number": ["图号", "图纸编号", "物料编码", "件号", "Drawing No", "DWG No"],
    # "revision": ["版本", "修订", "Rev", "Revision", "版次"],
    # "title": ["图名", "名称", "零件名称", "Title"],
    # "material": ["材料", "材质", "Material", "MAT"],
    # "scale": ["比例", "Scale"],
    # "date": ["日期", "出图日期", "Date"],
    # "designer": ["设计", "制图", "Design", "Drawn"],
    # "checker": ["审核", "校对", "Checked", "Check"],
    # "approver": ["批准", "审定", "Approved", "Approve"],
}


# ============================================================
# 5. Baseline 参数 / 严重度覆盖（企业 Override）
# ============================================================
# 企业标准优先于 Baseline：不修改 baseline_rules.py，而是在这里
# 覆盖某条 Baseline 规则的参数阈值或严重度。
# ============================================================

CUSTOM_OVERRIDES = [
    # LeRouge：DFM-004 薄壁阈值（企业默认 1.5mm，低于即提示）
    {
        "company": "LeRouge",
        "rule_id": "DFM-004",
        "parameter": "minimum_wall_thickness",
        "new_value": 1.5,
        "reason": "LeRouge 机加/钣金薄壁经验阈值",
        "standard_source": "LeRouge Drawing Audit Rules v1.0",
    },
]


# ============================================================
# 6. 企业自定义规则（追加到 28 条 Baseline 之后）
# ============================================================
# 与 Baseline 规则同构，追加进有效规则集，随 AI 审核一同执行。
#
# 扩展字段：
#   profile:     "A" / "B" / "AB"（归属 Profile，见文件头说明）
#   audit_round: "local"（分块审核）或 "comprehensive"（跨视图综合审核，默认）
#
# LeRouge 8 条核心红线（Profile A）+ 2 条母库缺口补充（Profile B）：
#   补充理由：母库 28 条无"视图/剖视缺失"与"退刀槽/越程槽缺失"对应规则，
#   为实现工厂清单 1:1 闭环，以 profile="B" 补入标准全功能档。
# ============================================================

CUSTOM_BASELINE_RULES = [
    # ── Profile A：LeRouge 8 条核心红线 ─────────────────────
    {
        "id": "LR-DIM-01",
        "name": "Closed Dimension Chain Intercept",
        "name_zh": "封闭尺寸链拦截",
        "category": "DIM",
        "category_name": "尺寸",
        "profile": "A",
        "audit_round": "comprehensive",
        "severity": "WARNING",
        "execution": "AI",
        "finding_type": "DRAWING_ERROR",
        "condition": "同一坐标方向各分段标注累加等于外形总尺寸，且均未标注参考符号（如 ( )）时触发。",
        "prompt": (
            "【LeRouge】仅审视图区。检查同一坐标方向上，各分段标注尺寸累加是否等于外形总尺寸，"
            "且各段均未标注参考符号（REF / ( ) / 参考）。若封闭尺寸链成立：报告该链，"
            "标注装配公差累积风险，建议断开非关键尺寸或改为参考尺寸。"
            "已显式标注为参考尺寸的链不触发。"
        ),
        "parameters": {},
        "enabled": True,
        "standard_source": "LeRouge Drawing Audit Rules v1.0",
    },
    {
        "id": "LR-TOL-02",
        "name": "Manufacturing Tolerance Economy",
        "name_zh": "制造公差经济性",
        "category": "TOL",
        "category_name": "公差",
        "profile": "A",
        "audit_round": "comprehensive",
        "severity": "WARNING",
        "execution": "AI",
        "finding_type": "COST_RISK",
        "condition": "车削/铣削常规工序中尺寸公差过紧（如常规轴颈 ≤ ±0.005mm），加工及质检成本激增。",
        "prompt": (
            "【LeRouge】检查机加件配合轴/定位销孔等常规工序尺寸的公差经济性。"
            "若车削/铣削常规工序公差过紧（如常规轴颈 ≤ ±0.005mm 或等效精度），"
            "提示加工及质检成本激增风险，并确认公差是否功能必需。"
            "避空/让位/退刀槽等非功能性尺寸不适用本条。"
        ),
        "parameters": {"tight_tolerance_threshold_mm": 0.005},
        "enabled": True,
        "standard_source": "LeRouge Drawing Audit Rules v1.0",
    },
    {
        "id": "LR-MEC-03",
        "name": "Thread Callout Completeness",
        "name_zh": "螺纹标注完整性",
        "category": "DIM",
        "category_name": "尺寸",
        "profile": "A",
        "audit_round": "comprehensive",
        "severity": "WARNING",
        "execution": "AI",
        "finding_type": "DRAWING_ERROR",
        "condition": "螺纹特征存在但缺代号（M/G/Tr/NPT）、规格、螺距或数量前缀（如多孔漏标 4-）。",
        "prompt": (
            "【LeRouge】仅审视图区。识别公制螺纹特征（3/4细实线圆弧、剖视牙底线、退刀槽），"
            "核验是否具备完整螺纹代号（M/G/Tr/NPT）、规格、螺距及数量前缀（如多孔漏标 4-）。"
            "单图光孔不做主观猜孔——仅当存在明确的螺纹特征证据（螺旋线/牙底线/螺纹符号）"
            "且无对应标注时报告。"
        ),
        "parameters": {},
        "enabled": True,
        "standard_source": "LeRouge Drawing Audit Rules v1.0",
    },
    {
        "id": "LR-MEC-04",
        "name": "Critical Fit Precision",
        "name_zh": "关键配合精度",
        "category": "TOL",
        "category_name": "公差",
        "profile": "A",
        "audit_round": "comprehensive",
        "severity": "WARNING",
        "execution": "AI",
        "finding_type": "DRAWING_ERROR",
        "condition": "轴承位/配合孔轴/导向面仅标公称尺寸，缺公差带代号（H7/g6）或上下极限偏差（±0.02）。",
        "prompt": (
            "【LeRouge】检查轴承安装位、配合孔轴、配合止口等关键配合位置。"
            "若仅标公称尺寸而缺少配合公差带代号（如 H7、g6）或上下极限偏差数值（如 ±0.02），"
            "判定配合公差缺失。避空/让位尺寸不适用。"
        ),
        "parameters": {},
        "enabled": True,
        "standard_source": "LeRouge Drawing Audit Rules v1.0",
    },
    {
        "id": "LR-GEO-05",
        "name": "GD&T Datum Closure",
        "name_zh": "形位公差与基准闭环",
        "category": "GDT",
        "category_name": "形位公差",
        "profile": "A",
        "audit_round": "comprehensive",
        "severity": "WARNING",
        "execution": "AI",
        "finding_type": "DRAWING_ERROR",
        "condition": "形位公差框格引用的基准代号（A/B/C）未在图面定义完整，或旋转轴承位/双导向孔缺同轴度/垂直度/平行度。",
        "prompt": (
            "【LeRouge】1. 框格基准闭环：形位公差框格引用的基准代号（如 [A|B]）必须在图面定义完整；"
            "若框格标注基准但图面无对应基准符号，判定基准缺失。"
            "2. 旋转轴承位/双导向孔若缺失同轴度、垂直度、平行度等形位公差，提示卡滞风险。"
            "基准符号若为纯图形（无文本层）且无法确认，用 NEEDS_REVIEW 而非直接报错。"
        ),
        "parameters": {},
        "enabled": True,
        "standard_source": "LeRouge Drawing Audit Rules v1.0",
    },
    {
        "id": "LR-SUR-06",
        "name": "Mating Surface Roughness",
        "name_zh": "配合面粗糙度",
        "category": "TOL",
        "category_name": "公差",
        "profile": "A",
        "audit_round": "comprehensive",
        "severity": "WARNING",
        "execution": "AI",
        "finding_type": "INSPECTION_RISK",
        "condition": "轴承装配档、导向滑动面未标注表面粗糙度符号，或标注数值 Ra > 1.6μm。",
        "prompt": (
            "【LeRouge】检查轴承装配档、导向滑动面等配合面："
            "未标注表面粗糙度符号，或标注数值 Ra > 1.6μm 时触发预警。"
            "非配合面不适用本条。"
        ),
        "parameters": {"max_ra_um": 1.6},
        "enabled": True,
        "standard_source": "LeRouge Drawing Audit Rules v1.0",
    },
    {
        "id": "LR-SHT-07",
        "name": "Sheet Metal Process Feasibility",
        "name_zh": "钣金工艺可行性",
        "category": "DFM",
        "category_name": "可制造性",
        "profile": "A",
        "audit_round": "comprehensive",
        "severity": "WARNING",
        "execution": "AI",
        "finding_type": "MANUFACTURING_RISK",
        "condition": "折弯内角未注或半径 R < 板厚 t；翻边孔边距小于折弯拉料变形安全距离（< 2t + R）。",
        "prompt": (
            "【LeRouge】钣金件：1. 折弯内圆角检查——折弯内角未注或半径 R < 板厚 t 时预警（防开裂）；"
            "2. 翻边孔边距检查——法兰孔边距小于折弯拉料变形安全距离（< 2t + R）时预警。"
            "需结合板厚判断，板厚信息缺失时用 NEEDS_REVIEW。"
        ),
        "parameters": {"min_bend_radius_ratio": 1.0, "flange_edge_safety_factor": 2.0},
        "enabled": True,
        "standard_source": "LeRouge Drawing Audit Rules v1.0",
    },
    {
        "id": "LR-MAT-08",
        "name": "Material & Surface Treatment Compatibility",
        "name_zh": "材质与表处兼容",
        "category": "MAT",
        "category_name": "材料/工艺",
        "profile": "A",
        "audit_round": "comprehensive",
        "severity": "WARNING",
        "execution": "AI",
        "finding_type": "MANUFACTURING_RISK",
        "condition": "碳钢裸件（Q235/45#）Treatment 留空缺防锈；铝件标镀铬/钢件标阳极氧化等工艺不匹配；6061 未标 -T6。",
        "prompt": (
            "【LeRouge】仅审视图区技术要求中的材料与表面处理文字（标题栏不审，但可用其提取结果）："
            "1. 碳钢裸件（Q235、45号钢）而表面处理栏留空 → 提示防锈缺失风险；"
            "2. 工艺匹配性：铝件严禁标镀铬、钢件严禁标阳极氧化；6061 铝合金未标状态（-T6）提示变形风险；"
            "发黑仅用于钢/铁而非铝。材料或表处信息缺失时用 NEEDS_REVIEW，不猜测。"
        ),
        "parameters": {},
        "enabled": True,
        "standard_source": "LeRouge Drawing Audit Rules v1.0",
    },

    # ── Profile B：母库缺口补充（1:1 闭环） ─────────────────
    {
        "id": "LR-VIEW-09",
        "name": "Missing Required View / Section",
        "name_zh": "必要视图/剖视缺失",
        "category": "DOC",
        "category_name": "图纸完整性",
        "profile": "B",
        "audit_round": "comprehensive",
        "severity": "WARNING",
        "execution": "AI",
        "finding_type": "AMBIGUITY",
        "condition": "内部特征（内腔、油道、盲孔系、沉头孔、加强筋）无对应剖视/局部放大视图，无法完整表达。",
        "prompt": (
            "检查内部特征（内腔、油道、盲孔系、沉头孔、加强筋等）是否有对应的剖视图/局部放大图表达。"
            "若内部特征无法从现有视图完整解读且无剖视/局部放大，提示补充视图。"
            "无法确认内部结构存在时用 NEEDS_REVIEW，不猜测。"
        ),
        "parameters": {},
        "enabled": True,
        "standard_source": "GZ-020 工程图AI审查清单 #23",
    },
    {
        "id": "LR-MEC-10",
        "name": "Missing Relief / Undercut Groove",
        "name_zh": "退刀槽/越程槽缺失",
        "category": "DFM",
        "category_name": "可制造性",
        "profile": "B",
        "audit_round": "comprehensive",
        "severity": "WARNING",
        "execution": "AI",
        "finding_type": "MANUFACTURING_RISK",
        "condition": "螺纹收尾、磨削外圆、插齿/台阶靠肩交接处缺少退刀槽/越程槽，致无法加工或刀具干涉。",
        "prompt": (
            "检查螺纹收尾、磨削外圆、插齿及台阶靠肩交接处是否缺少退刀槽/越程槽。"
            "缺失可能导致无法加工或刀具干涉。仅在存在明确加工特征（螺纹、磨削面、台阶靠肩）"
            "且根部无退刀槽/越程槽时报告；无法判断时用 NEEDS_REVIEW。"
        ),
        "parameters": {},
        "enabled": True,
        "standard_source": "GZ-020 工程图AI审查清单 #20",
    },
]