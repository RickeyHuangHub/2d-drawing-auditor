"""
============================================================
  自定义审图规则与技术要求配置
  ============================================================
  这是你添加自定义规则的唯一入口。修改后重启服务即可生效。

  五个区域：
  1. CUSTOM_CHECKLIST       — 自定义 AI 检查项（需要 AI 看图纸判断的）
  2. CUSTOM_TECH_REQS       — 自定义技术要求（注入 AI 提示词作为审核依据）
  3. CUSTOM_RULE_CHECKS     — 自定义规则检查（正则匹配 PDF 文本，零误差）
  4. CUSTOM_OVERRIDES       — Baseline 参数/严重度覆盖（企业标准优先于 Baseline）
  5. CUSTOM_BASELINE_RULES  — 企业自定义规则（追加到 28 条 Baseline 之后）

  规则优先级：Project > Customer > Company > Baseline。
  企业不应直接修改 baseline_rules.py，应通过 4/5 两个区域扩展。
============================================================
"""

# ============================================================
# 1. 自定义 AI 检查项
# ============================================================
# 每条检查项会作为独立条目出现在前端"审核标准"弹窗中，
# 并作为 prompt 传给 AI 视觉模型逐项审查。
#
# 字段说明：
#   id:          唯一标识（英文，用下划线）
#   name:        检查项名称（中文，前端显示）
#   enabled:     是否默认启用
#   description: 检查要点描述（AI 会据此审查，写得越具体越好）
#   severity:    默认严重等级（block / warning / info）
#
# 示例已注释，取消注释即可使用。
# ============================================================

CUSTOM_CHECKLIST = [
    # {
    #     "id": "company_drawing_standard",
    #     "name": "公司制图标准",
    #     "enabled": True,
    #     "description": "检查是否符合我司《工程制图规范V2.1》：图框用A系列标准图框，"
    #                    "标题栏位于右下角，尺寸标注采用对齐方式，文字高度不小于3.5mm，"
    #                    "中心线用点划线，不可见轮廓用虚线。",
    #     "severity": "warning",
    # },
    # {
    #     "id": "surface_treatment",
    #     "name": "表面处理要求",
    #     "enabled": True,
    #     "description": "检查表面处理标注是否齐全：钢制零件需注明氧化/发黑/镀锌等处理方式；"
    #                    "铝合金零件需注明阳极氧化/喷砂等；塑料零件需注明皮纹号（如 MT11010）。"
    #                    "表面粗糙度 Ra 值需与表面处理方式匹配。",
    #     "severity": "warning",
    # },
    # {
    #     "id": "thread_standard",
    #     "name": "螺纹标注规范",
    #     "enabled": False,
    #     "description": "检查螺纹标注是否符合 GB/T 197 标准：普通螺纹标注格式为 M10-6H，"
    #                    "管螺纹标注 G1/2，梯形螺纹标注 Tr40×7。螺纹有效长度需标注，"
    #                    "螺纹孔需标注钻孔深度和攻丝深度。",
    #     "severity": "warning",
    # },
]


# ============================================================
# 2. 自定义技术要求（注入 AI 提示词）
# ============================================================
# 这里写的内容会作为"审核依据"附加在 AI 系统提示词中。
# 适合放：行业标准条款、公司工艺规范、材料特殊要求等。
# AI 在审核每张图纸时都会参考这些要求。
#
# 用列表形式，每条一段。写得越具体，AI 审核越精准。
# ============================================================

CUSTOM_TECH_REQS = [
    # "【公司标准】所有图纸必须符合《XX公司工程制图规范V2.1》，"
    # "图框采用GB/T 14689标准A系列图框，标题栏格式按公司模板。",

    # "【公差标准】未注尺寸公差按 GB/T 1804-m，未注形位公差按 GB/T 1184-K。"
    # "配合公差优先采用基孔制，公差等级一般孔取 H7、轴取 g6/h6/k6/n6。",

    # "【材料规范】结构件优先选用 Q235B 或 304 不锈钢；"
    # "铝合金件优先选用 6061-T6；紧固件采用 8.8 级以上碳钢或 A2-70 不锈钢。"
    # "材料变更需在变更记录中注明。",

    # "【工艺要求】钣金件折弯内角半径不小于板厚；"
    # "机加工件需标注表面粗糙度，配合面 Ra≤1.6，非配合面 Ra≤6.3；"
    # "焊接件需标注焊缝符号和焊脚高度。",
]


# ============================================================
# 3. 自定义规则检查（正则匹配 PDF 矢量文本）
# ============================================================
# 对于可以用文字匹配精确判断的规则，在这里定义正则表达式。
# 系统会从 PDF 中提取矢量文本，用这些正则检查。
# 比 AI 判断更准确、零成本、不会漏。
#
# 字段说明：
#   id:          唯一标识
#   name:        规则名称
#   category:    所属检查项分类（对应 checklist id）
#   severity:    严重等级（block / warning / info）
#   pattern:     正则表达式（匹配到 = 存在/合规）
#   mode:        "must_exist"（必须存在，匹配不到则报错）
#                或 "must_not_exist"（不能存在，匹配到则报错）
#   title:       报错标题
#   description: 报错详细描述
#   suggestion:  修改建议
#
# 示例已注释，取消注释即可使用。
# ============================================================

CUSTOM_RULE_CHECKS = [
    # {
    #     "id": "company_drawing_number_format",
    #     "name": "公司图号格式校验",
    #     "category": "title_block",
    #     "severity": "block",
    #     "mode": "must_exist",
    #     "pattern": r"[A-Z]{2,3}-\d{3,4}-[A-Z]\d?",
    #     "title": "图号不符合公司格式",
    #     "description": "公司图号标准格式为：项目缩写(2-3字母)-序号(3-4位)-版本(字母+数字)，"
    #                    "例如 AB-001-A1。当前图纸未检测到符合格式的图号。",
    #     "suggestion": "请按公司图号编码规则修改标题栏中的图号。",
    # },
    # {
    #     "id": "must_have_untoleranced_note",
    #     "name": "未注公差说明必须存在",
    #     "category": "tolerance",
    #     "severity": "warning",
    #     "mode": "must_exist",
    #     "pattern": r"(未注公差|GB/T\s*1804|一般公差)",
    #     "title": "缺少未注公差说明",
    #     "description": "技术要求中未注明未注公差标准，加工时无据可依。",
    #     "suggestion": "在技术要求中添加：未注尺寸公差按 GB/T 1804-m，"
    #                   "未注形位公差按 GB/T 1184-K。",
    # },
    # {
    #     "id": "no_placeholder_text",
    #     "name": "禁止占位符文字",
    #     "category": "drafting",
    #     "severity": "block",
    #     "mode": "must_not_exist",
    #     "pattern": r"(TODO|待填|XXX|占位|placeholder|TBD)",
    #     "title": "图纸中存在占位符文字",
    #     "description": "检测到图纸中存在未完成的占位符文字（TODO/待填/XXX等），"
    #                    "说明图纸尚未完成，不能用于生产。",
    #     "suggestion": "请补全所有占位符内容，确认图纸完成后再发布。",
    # },
    # {
    #     "id": "material_must_be_specified",
    #     "name": "材料牌号必须标注",
    #     "category": "title_block",
    #     "severity": "block",
    #     "mode": "must_exist",
    #     "pattern": r"(Q235|Q345|45#|304|316|6061|7075|5052|ABS|PC|PP|POM|PMMA|PA66|铝合金|不锈钢|碳钢)",
    #     "title": "未标注材料牌号",
    #     "description": "标题栏或技术要求中未检测到标准材料牌号，无法指导采购和加工。",
    #     "suggestion": "请在标题栏材料栏填写完整材料牌号，如 Q235B、304、AL6061-T6 等。",
    # },
]


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
# 4. Baseline 参数 / 严重度覆盖（企业 Override）
# ============================================================
# 企业标准优先于 Baseline：不修改 baseline_rules.py，而是在这里
# 覆盖某条 Baseline 规则的参数阈值或严重度。
#
# 字段说明：
#   company         企业/来源名称（用于报告溯源）
#   rule_id         被覆盖的 Baseline 规则 ID（如 DFM-002）
#   parameter       被覆盖的参数名（对应规则 parameters 中的 key）
#   new_value       新参数值
#   severity        可选：覆盖严重度（CRITICAL / WARNING / INFO）
#   reason          覆盖理由（写入报告，便于追溯）
#   standard_source 企业标准来源（如 "ABC Drawing Standard DS-001 Rev.C"）
#
# 示例已注释，取消注释即可使用。
# ============================================================

CUSTOM_OVERRIDES = [
    # {
    #     "company": "ABC Manufacturing",
    #     "rule_id": "DFM-002",
    #     "parameter": "maximum_hole_depth_ratio",
    #     "new_value": 4.0,
    #     "severity": "WARNING",
    #     "reason": "ABC internal machining standard",
    #     "standard_source": "ABC Drawing Standard DS-001 Rev.C",
    # },
    # {
    #     "company": "ABC Manufacturing",
    #     "rule_id": "DFM-001",
    #     "parameter": "minimum_edge_distance_ratio",
    #     "new_value": 1.5,
    #     "reason": "本司钣金冲压工艺要求孔边距更保守",
    #     "standard_source": "ABC-DS-002 Rev.B",
    # },
]


# ============================================================
# 5. 企业自定义规则（追加到 28 条 Baseline 之后）
# ============================================================
# 与 Baseline 规则同构，追加进有效规则集，随 AI 审核一同执行。
#
# 字段说明（与 baseline_rules.py 的 BASELINE_RULES 一致）：
#   id              唯一规则 ID（建议用企业前缀，如 ABC-DIM-001）
#   name            规则英文名
#   name_zh         规则中文名
#   category        大类（DOC/DIM/TOL/GDT/MAT/DFM/REV）
#   category_name   大类中文名
#   severity        CRITICAL / WARNING / INFO
#   execution       Deterministic（程序可算，需在 rule_engine.py 实现）
#                   / Hybrid（规则+AI）/ AI（AI 综合）
#   finding_type    DRAWING_ERROR / AMBIGUITY / MANUFACTURING_RISK
#                   / COST_RISK / INSPECTION_RISK / DOCUMENT_CONTROL
#   condition       触发/判断条件
#   prompt          AI 可逐条执行的审核指令（写清楚，AI 会照着做）
#   parameters      可覆盖参数
#   enabled         默认是否启用
#   standard_source 企业标准来源
#
# 示例已注释，取消注释即可使用。
# ============================================================

CUSTOM_BASELINE_RULES = [
    # {
    #     "id": "ABC-DIM-001",
    #     "name": "Mounting Hole Minimum Edge Distance",
    #     "name_zh": "安装孔最小边距",
    #     "category": "DIM",
    #     "category_name": "尺寸",
    #     "severity": "CRITICAL",
    #     "execution": "Hybrid",
    #     "finding_type": "MANUFACTURING_RISK",
    #     "condition": "安装孔边距 < 8 mm",
    #     "prompt": (
    #         "Verify that every mounting hole has an edge distance of at least 8 mm "
    #         "from the nearest part edge. If edge distance < 8 mm: CRITICAL. "
    #         "Report the measured edge distance as evidence."
    #     ),
    #     "parameters": {"minimum_edge_distance_mm": 8.0},
    #     "enabled": True,
    #     "standard_source": "ABC Drawing Standard DS-001 Rev.C",
    # },
]
