"""
规则前置检查模块（Rule-based Pre-check）
- 利用 PDF 矢量文本层，用正则/规则校验标题栏信息
- 减轻 AI 视觉模型压力，提高文字类信息准确率
"""
import re
from typing import List, Dict, Any, Tuple, Optional

from config import CUSTOM_RULE_CHECKS, CUSTOM_TITLE_BLOCK_FIELDS
from .models import IssueItem, Severity


class RuleChecker:
    """规则检查器"""

    def __init__(self):
        self.issues: List[IssueItem] = []
        self.title_block_info: Dict[str, Any] = {}

    def run(self, extracted_text: str,
            title_block_text: Optional[str] = None) -> Tuple[List[IssueItem], Dict[str, Any]]:
        """
        执行全部规则检查。
        参数:
          extracted_text   : 全文矢量文本（结构性检查使用）
          title_block_text : 标题栏坐标限定区域文本（标题栏字段优先在此识别，
                             未命中时回退全文，避免漏判；为 None 时全部用全文）
        返回: (问题列表, 标题栏提取信息)
        """
        self.issues = []
        self.title_block_info = {}

        if not extracted_text or not extracted_text.strip():
            self._add_issue(
                category="title_block",
                category_name="图框与标题栏",
                severity=Severity.WARNING,
                title="未检测到矢量文本层",
                description="该 PDF 不包含可提取的矢量文本，可能是扫描件或纯图片PDF。标题栏信息将完全依赖AI视觉识别，准确率可能下降。",
                suggestion="如有条件，请提供矢量格式的PDF（如从CAD直接导出），或确保图纸文字清晰。",
                source="rule"
            )
            return self.issues, self.title_block_info

        full = extracted_text
        # 标题栏区域文本：有则优先用于标题栏字段识别，否则回退全文
        tb = title_block_text if (title_block_text and title_block_text.strip()) else None

        # 标题栏字段：优先标题栏区域，未命中回退全文（降误报且不漏判）
        self._check_drawing_number(tb, full)
        self._check_revision(tb, full)
        self._check_title(tb, full)
        self._check_material(tb, full)
        self._check_scale(tb, full)
        self._check_signature(tb, full)
        self._check_date(tb, full)

        # 结构性/技术性检查：作用于全文
        self._check_untoleranced_dimensions(full)
        self._check_duplicate_text(full)
        self._check_custom_rules(full)

        return self.issues, self.title_block_info

    # ── 搜索工具（标题栏优先 + 全文回退）──────────────────────

    # 已知标题栏标签文字（中英文），用于排除"把标签当值"的误提取
    _LABEL_RE = re.compile(
        r'^(?:PartNo\.?|Dwg\.?\s*No\.?|Drawing|Material|Quantity|'
        r'Treatment|Weight|PartName|Date|Scale|FIRST|ANGLE|PROJ\.?|'
        r'图号|料号|名称|材料|数量|处理|单重|绘图|日期|比例|第一视角|'
        r'共\s*张|第\s*张|乐虹|智能科技|有限公司|科技|有限|公司|'
        r'Lerouge|Intelligent|Technology|Co\.?,?\s*Ltd\.?|kg|mm)$',
        re.IGNORECASE
    )

    @classmethod
    def _is_label_text(cls, val: str) -> bool:
        """判断提取到的值是否是已知的标题栏标签文字（用于排除误提取）"""
        if not val:
            return True
        v = val.strip()
        if len(v) <= 1:
            return True
        return bool(cls._LABEL_RE.match(v))

    @staticmethod
    def _search_any(patterns, text: Optional[str], flags=0):
        """在 text 中依次尝试 patterns，返回第一个匹配的 (pattern, match)，无则 None"""
        if not text:
            return None
        for pat in patterns:
            m = re.search(pat, text, flags)
            if m:
                return pat, m
        return None

    @classmethod
    def _match_first(cls, patterns, primary: Optional[str],
                     fallback: Optional[str], flags=0):
        """优先在 primary 中搜索；未命中且 fallback 存在时回退到 fallback"""
        hit = cls._search_any(patterns, primary, flags)
        if hit:
            return hit
        if fallback and fallback != primary:
            return cls._search_any(patterns, fallback, flags)
        return None

    # ── 各项规则检查 ───────────────────────────────────────────

    def _check_drawing_number(self, primary: Optional[str], fallback: Optional[str]):
        """检查图号/物料编码 → Baseline DOC-001"""
        # 常见图号格式：字母-数字-字母 或 纯数字编码
        # 注意：物料编码格式优先匹配（避免把标签文字当值）
        patterns = [
            # 通用物料编码：2+大写字母开头，后跟连字符和字母数字段，如 GZ-Y008-LH24-0251、ABC-001-A
            (r'\b([A-Z]{2,}-[A-Za-z0-9]{2,10}(?:-[A-Za-z0-9]{2,10}){1,4})\b', "物料编码格式"),
            (r'(?:图号|Drawing No|DWG No|件号|零件号|Part No)\s*[:：]?\s*([A-Za-z0-9\-_/.]+)', "标准标签"),
            (r'\b(\d{6,12})\b', "数字编码"),
        ]

        found = False
        for pattern, ptype in patterns:
            hit = self._match_first([pattern], primary, fallback, re.IGNORECASE)
            if hit:
                _, m = hit
                val = m.group(1) if m.lastindex else m.group(0)
                # 排除已知标签文字（如 "PartNo." 被误当值）
                if self._is_label_text(val):
                    continue
                self.title_block_info["drawing_number"] = val
                self.title_block_info["drawing_number_type"] = ptype
                found = True
                break

        if not found:
            self._add_issue(
                id="rule_DOC-001",
                rule_id="DOC-001",
                rule_name="Drawing / Part Number Missing",
                finding_type="DOCUMENT_CONTROL",
                category="DOC",
                category_name="图纸完整性",
                severity=Severity.BLOCK,
                title="未找到图号/物料编码",
                description="在图纸文本中未检测到标准格式的图号或物料编码。图号是图纸的唯一标识，缺失将导致无法追溯和归档。",
                suggestion="请在标题栏中填写图号，推荐格式：项目缩写-序号-版本（如 ABC-001-A）。",
                location="标题栏",
                source="rule"
            )

    def _check_revision(self, primary: Optional[str], fallback: Optional[str]):
        """检查版本号"""
        # 版本格式：Rev A / 版本 A / REV.1 / A
        rev_patterns = [
            r'[Rr]ev(?:ision)?\.?\s*[:：]?\s*([A-Z]|\d{1,2})',
            r'版本\s*[:：]?\s*([A-Z]|\d{1,2})',
            r'\b([A-Z])\s*\b(?=\s*(?:日期|签名))',  # 日期签名旁的单字母
        ]

        hit = self._match_first(rev_patterns, primary, fallback)
        if hit:
            _, m = hit
            self.title_block_info["revision"] = m.group(1) if m.lastindex else m.group(0)
            return

        self._add_issue(
            id="rule_REV-001",
            rule_id="REV-001",
            rule_name="Revision Missing / Invalid",
            finding_type="DOCUMENT_CONTROL",
            category="REV",
            category_name="版本/文件控制",
            severity=Severity.BLOCK,
            title="未找到版本号",
            description="标题栏中未检测到版本/修订号。版本管理是工程变更控制的基础。",
            suggestion="请在标题栏填写版本号（如 Rev A / 版本 1），并在变更记录栏更新变更内容。",
            location="标题栏",
            source="rule"
        )

    def _check_title(self, primary: Optional[str], fallback: Optional[str]):
        """检查图名/名称"""
        title_patterns = [
            r'(?:图名|名称|零件名称|Title|PartName)\s*[:：]?\s*(.+)',
        ]

        hit = self._match_first(title_patterns, primary, fallback)
        if hit:
            _, m = hit
            title = m.group(1).strip() if m.lastindex else m.group(0).strip()
            # 排除已知标签文字（如把下一个标签 "材料" 误当图名）
            if 2 < len(title) < 100 and not self._is_label_text(title):
                self.title_block_info["title"] = title
                return

        # 如果没找到标准标签，检查是否有任何中文标题（3-20字）
        # 这是宽松检查，不报错
        pass

    def _check_material(self, primary: Optional[str], fallback: Optional[str]):
        """检查材料"""
        material_patterns = [
            r'(?:材料|材质|Material|MAT)\s*[:：]?\s*([A-Za-z0-9\u4e00-\u9fa5\s\-/.]+?)(?=\n|$)',
        ]

        # 常见材料关键词
        material_keywords = [
            'Q235', 'Q345', '45#', '45号钢', '304', '316', '316L',
            'AL6061', '6061', '7075', '5052', 'ABS', 'PC', 'PP', 'PE',
            'POM', 'PMMA', 'PA66', 'PA6', 'PBT', '铝合金', '不锈钢',
            '碳钢', '铜', '黄铜', '紫铜', '钛合金', '铸铁', '铸钢',
            'SUS304', 'SUS316', 'AL6061-T6', '6061-T6', '6061 合金',
            '45钢', 'Cr12', 'Cr12MoV', 'SKD11', 'DC53', 'H13', 'P20',
            '718H', 'NAK80', 'S136', '2344', '2316', '2083', '2738',
            '6061铝合金', '6063', '5052铝合金', '5083', '7075铝合金',
            '2A12', '2024', 'LY12', 'TC4', 'TA1', 'TA2', '纯铜',
            '铍铜', '磷青铜', '锡青铜', '铝青铜', '硬质合金', '钨钢',
        ]

        found = False
        # 第一步：优先在标题栏区域用材料关键词匹配（最可靠）
        for text_cand in (primary, fallback):
            if not text_cand or found:
                continue
            for kw in material_keywords:
                if kw.lower() in text_cand.lower():
                    self.title_block_info["material"] = kw
                    found = True
                    break

        # 第二步：关键词未命中时，用标准标签正则匹配（排除标签文字）
        if not found:
            hit = self._match_first(material_patterns, primary, fallback, re.IGNORECASE)
            if hit:
                _, m = hit
                mat = m.group(1).strip() if m.lastindex else m.group(0).strip()
                if mat and len(mat) < 50 and not self._is_label_text(mat):
                    self.title_block_info["material"] = mat
                    found = True

        if not found:
            self._add_issue(
                id="rule_DOC-003",
                rule_id="DOC-003",
                rule_name="Material Specification Missing",
                finding_type="DOCUMENT_CONTROL",
                category="DOC",
                category_name="图纸完整性",
                severity=Severity.BLOCK,
                title="未找到材料信息",
                description="标题栏中未检测到材料/材质标注。材料是加工和采购的关键信息。",
                suggestion="请在标题栏填写材料牌号（如 304不锈钢、AL6061、Q235等）。",
                location="标题栏",
                source="rule"
            )

    def _check_scale(self, primary: Optional[str], fallback: Optional[str]):
        """检查比例"""
        scale_patterns = [
            r'(?:比例|Scale)\s*[:：]?\s*(\d+\s*[:：]\s*\d+)',
            r'\b(\d+\s*:\s*\d+)\b',
        ]

        hit = self._match_first(scale_patterns, primary, fallback)
        if hit:
            _, m = hit
            val = m.group(1).replace(" ", "") if m.lastindex else m.group(0).replace(" ", "")
            self.title_block_info["scale"] = val
            return

        self._add_issue(
            category="title_block",
            category_name="图框与标题栏",
            severity=Severity.INFO,
            title="未找到比例标注",
            description="标题栏中未检测到绘图比例。虽然1:1出图时可省略，但建议明确标注。",
            suggestion="如非1:1出图，请在标题栏填写比例（如 1:2、2:1）。",
            location="标题栏",
            source="rule"
        )

    def _check_signature(self, primary: Optional[str], fallback: Optional[str]):
        """检查签名栏"""
        sig_labels = ['设计', '制图', '审核', '批准', '校对', '工艺',
                      'Design', 'Drawn', 'Checked', 'Approved']

        empty_sig = []
        for label in sig_labels:
            # 查找标签后是否有签名（非空字符），[ \t]* 不跨行
            pattern = rf'{label}[ \t]*[:：]?[ \t]*(\S+)?'
            hit = self._match_first([pattern], primary, fallback)
            if hit:
                _, m = hit
                sig = m.group(1).strip() if m.lastindex and m.group(1) else ""
                if not sig or sig in ('/', '-', '—', '无'):
                    empty_sig.append(label)

        if empty_sig:
            severity = Severity.BLOCK if '审核' in empty_sig or '批准' in empty_sig else Severity.WARNING
            self._add_issue(
                category="title_block",
                category_name="图框与标题栏",
                severity=severity,
                title=f"签名栏未填写: {', '.join(empty_sig[:3])}",
                description=f"以下签名栏为空或未填写: {', '.join(empty_sig)}。工程图纸需要完整的签审流程。",
                suggestion="请补全设计、制图、审核、批准等签名栏信息。",
                location="标题栏签名区",
                source="rule"
            )

    def _check_date(self, primary: Optional[str], fallback: Optional[str]):
        """检查日期"""
        date_patterns = [
            r'(\d{4})\s*[年\-/.]\s*(\d{1,2})\s*[月\-/.]\s*(\d{1,2})\s*日?',
            r'(\d{1,2})\s*[/\-]\s*(\d{1,2})\s*[/\-]\s*(\d{2,4})',
        ]

        hit = self._match_first(date_patterns, primary, fallback)
        if hit:
            _, m = hit
            self.title_block_info["date"] = "-".join(m.groups())
            return

        self._add_issue(
            category="title_block",
            category_name="图框与标题栏",
            severity=Severity.INFO,
            title="未找到出图日期",
            description="标题栏中未检测到出图/设计日期。日期有助于追溯图纸时效性。",
            suggestion="请在标题栏填写出图日期（如 2026-08-30）。",
            location="标题栏",
            source="rule"
        )

    def _check_untoleranced_dimensions(self, text: str):
        """检查是否有未注公差说明"""
        keywords = ['未注公差', '未注尺寸公差', '未注形位公差', '一般公差',
                    'untoleranced', 'general tolerance', 'ISO 2768', 'GB/T 1804']

        found = any(kw.lower() in text.lower() for kw in keywords)
        if not found:
            self._add_issue(
                id="rule_TOL-001",
                rule_id="TOL-001",
                rule_name="General Tolerance Undefined",
                finding_type="DRAWING_ERROR",
                category="TOL",
                category_name="公差",
                severity=Severity.WARNING,
                title="缺少未注公差说明",
                description="技术要求中未检测到未注公差/一般公差说明。未标注公差的尺寸将缺乏加工依据。",
                suggestion="请在技术要求中注明未注公差标准，如：未注尺寸公差按 GB/T 1804-m，未注形位公差按 GB/T 1184-K。",
                location="技术要求区",
                source="rule"
            )

    def _check_duplicate_text(self, text: str):
        """检查重复文本（可能的标注错误）"""
        # 简单检查：同一行出现重复的数字标注
        lines = text.split('\n')
        for line in lines:
            line = line.strip()
            if len(line) < 3 or len(line) > 50:
                continue
            # 检查重复 token
            tokens = re.findall(r'[\u4e00-\u9fa5A-Za-z0-9.]+', line)
            if len(tokens) >= 2:
                from collections import Counter
                counts = Counter(tokens)
                duplicates = [t for t, c in counts.items() if c > 1 and len(t) > 1]
                if duplicates and len(duplicates) <= 2:
                    # 可能是重复标注，但也可能是正常文本，只做 info 级提示
                    pass  # 过于严格会误报，暂时跳过

    def _check_custom_rules(self, text: str):
        """
        执行自定义规则检查（从 custom_rules.py 的 CUSTOM_RULE_CHECKS 加载）。
        支持两种模式：
        - must_exist: 正则必须匹配到，否则报错
        - must_not_exist: 正则不能匹配到，匹配到则报错
        """
        if not CUSTOM_RULE_CHECKS:
            return

        for rule in CUSTOM_RULE_CHECKS:
            try:
                pattern = rule.get("pattern", "")
                mode = rule.get("mode", "must_exist")
                matches = re.findall(pattern, text, re.IGNORECASE | re.MULTILINE)

                if mode == "must_exist" and not matches:
                    # 必须存在但没找到 → 报错
                    self._add_issue(
                        id=f"custom_{rule.get('id', 'unknown')}",
                        rule_id=rule.get("id", "CUSTOM"),
                        rule_name=rule.get("name", "自定义规则"),
                        finding_type="DOCUMENT_CONTROL",
                        category=rule.get("category", "custom"),
                        category_name=rule.get("name", "自定义规则"),
                        severity=Severity(rule.get("severity", "warning")),
                        title=rule.get("title", "自定义规则未通过"),
                        description=rule.get("description", ""),
                        suggestion=rule.get("suggestion", ""),
                        location=rule.get("location", "全文"),
                        source="rule",
                    )
                elif mode == "must_not_exist" and matches:
                    # 不能存在但找到了 → 报错
                    matched_text = matches[0] if matches else ""
                    if isinstance(matched_text, tuple):
                        matched_text = " ".join(str(x) for x in matched_text if x)
                    self._add_issue(
                        id=f"custom_{rule.get('id', 'unknown')}",
                        rule_id=rule.get("id", "CUSTOM"),
                        rule_name=rule.get("name", "自定义规则"),
                        finding_type="DOCUMENT_CONTROL",
                        category=rule.get("category", "custom"),
                        category_name=rule.get("name", "自定义规则"),
                        severity=Severity(rule.get("severity", "warning")),
                        title=rule.get("title", "自定义规则未通过"),
                        description=f"{rule.get('description', '')} 匹配到: \"{str(matched_text)[:50]}\"",
                        suggestion=rule.get("suggestion", ""),
                        location=rule.get("location", "全文"),
                        source="rule",
                    )
            except Exception as e:
                # 自定义规则出错不影响整体审核
                print(f"自定义规则 {rule.get('id', '?')} 执行出错: {e}")

    # ── 工具方法 ───────────────────────────────────────────────

    def _add_issue(self, **kwargs):
        """添加一条问题"""
        # 如果传入了自定义 id 则使用，否则自动生成
        issue_id = kwargs.pop("id", f"rule_{len(self.issues) + 1:03d}")
        kwargs.setdefault("standard_source", "BASELINE")
        issue = IssueItem(
            id=issue_id,
            **kwargs
        )
        self.issues.append(issue)
