"""
============================================================
  Baseline V1.0 规则引擎（确定性规则）
  ============================================================
  负责 10 步流水线中的：
    ③ 加载 28 条 Baseline
    ④ 加载企业 Override / Custom Rules
    ⑤ Deterministic 先算（程序执行，不依赖 AI）
    ⑧ Evidence 验证（No Evidence → No Finding）

  确定性规则由程序计算：
    - DOC-001  图号/零件号缺失（文本层判定）
    - REV-001  版本号缺失/无效（文本层判定）
    - GDT-001  特征控制框引用基准是否存在（文本层最佳努力）
    - DFM-001  孔边距风险（E/D，需文本含边距与孔径）
    - DFM-002  深孔风险（L/D，需文本含孔径与深度）

  Hybrid / AI 规则由 ai_auditor.py 注入视觉大模型执行。
============================================================
"""
import re
from typing import List, Dict, Any, Optional, Tuple

from config import SEVERITY_MAP, CUSTOM_RULE_CHECKS
from baseline_rules import FINDING_TYPES
from .models import IssueItem, Severity


# ── 结构化 finding 构造器 ─────────────────────────────────────
def build_finding(rule: Dict[str, Any], *,
                  result: str = "WARNING",
                  title: Optional[str] = None,
                  description: Optional[str] = None,
                  evidence: Optional[List[str]] = None,
                  location: str = "",
                  location_view: str = "",
                  location_feature: str = "",
                  page: int = 0,
                  calculation: Optional[Dict[str, Any]] = None,
                  confidence: float = 1.0,
                  requires_human_review: bool = False,
                  suggestion: str = "",
                  engineering_risk: str = "",
                  source: str = "deterministic") -> Optional[IssueItem]:
    """
    根据规则 + 计算结果构造结构化 finding。
    符合 Baseline 的 EVIDENCE POLICY：
    - PASS / NOT_APPLICABLE → 不产生 finding
    - NEEDS_REVIEW → 强制 requires_human_review=True
    """
    if result in ("PASS", "NOT_APPLICABLE"):
        return None

    severity_value = SEVERITY_MAP.get(rule.get("severity", "WARNING"), "warning")
    if result == "NEEDS_REVIEW":
        requires_human_review = True
        # NEEDS_REVIEW 属于证据不足，不按 CRITICAL 阻断处理
        if severity_value == "block":
            severity_value = "warning"

    rule_id = rule.get("id", "")
    rule_name = rule.get("name", "")
    finding_type = rule.get("finding_type", "DRAWING_ERROR")

    # TOL-003 特殊要求：输出标记为 Cost / Manufacturability Risk，而非图纸错误
    if rule_id == "TOL-003":
        finding_type = "COST_RISK"

    issue = IssueItem(
        id=f"{source}_{rule_id}_{abs(hash((rule_id, location, page))) % 10_000_000:07d}",
        category=rule.get("category", ""),
        category_name=rule.get("category_name", ""),
        severity=Severity(severity_value),
        title=title or rule.get("name_zh", rule_name),
        description=description or rule.get("condition", ""),
        location=location,
        suggestion=suggestion,
        page=page,
        source=source,
        rule_id=rule_id,
        rule_name=rule_name,
        finding_type=finding_type,
        result=result,
        confidence=confidence,
        evidence=evidence or [],
        parameters=dict(rule.get("parameters", {})),
        calculation=calculation or {},
        engineering_risk=engineering_risk,
        standard_source=rule.get("standard_source", "BASELINE"),
        requires_human_review=requires_human_review,
        location_view=location_view,
        location_feature=location_feature,
    )
    return issue


# ── 工程文本解析工具 ──────────────────────────────────────────

_DIA_RE = re.compile(
    r'(?:Ø|φ|Φ|DIA\.?|DIAM\.?|直径)\s*(\d+(?:\.\d+)?)', re.IGNORECASE)
_DEPTH_RE = re.compile(
    r'(?:深|深度|钻深|DEEP|DEPTH|至深)\s*(\d+(?:\.\d+)?)', re.IGNORECASE)
_EDGE_RE = re.compile(
    r'(?:边距|距边|边缘距离|孔边距|EDGE\s*(?:DIST|DISTANCE|DIS)?\.?)\s*(?:≥|>=|>|=|:)?\s*(\d+(?:\.\d+)?)', re.IGNORECASE)
# 直径符号（CAD 导出时常被丢弃，只保留数字）
_DIA_OPT = r'(?:Ø|φ|Φ|DIA\.?|DIAM\.?|直径)?'
# 模式A：直径 深深度；直径前不能是"数量×"（避免把数量误当孔径）
_HOLE_DEPTH_PAT = re.compile(
    _DIA_OPT + r'\s*(?<![×xX*0-9])(\d+(?:\.\d+)?)\s*'
    r'(?:深|深度|钻深|至深|DEEP|DEPTH)\s*(\d+(?:\.\d+)?)', re.IGNORECASE)
_QTY_DIA_DEPTH_PAT = re.compile(
    r'(\d+)\s*[×xX*]\s*' + _DIA_OPT + r'\s*(\d+(?:\.\d+)?)\s*'
    r'(?:深|深度|钻深|至深|DEEP|DEPTH)\s*(\d+(?:\.\d+))?', re.IGNORECASE)


def parse_diameters(text: str) -> List[float]:
    """提取所有孔径（Ø/φ/DIA 后数字）"""
    return [float(m) for m in _DIA_RE.findall(text)]


def parse_depths(text: str) -> List[float]:
    """提取所有深度值"""
    return [float(m) for m in _DEPTH_RE.findall(text)]


def parse_hole_pairs(text: str) -> List[Dict[str, float]]:
    """
    解析 孔径+深度 成对出现的深孔规格。兼容 CAD 导出时 Ø 符号被丢弃的情况。
    支持：Ø3 深22 / 3 深22 / φ6 DEEP 30 / DIA 3.5 深25 / Ø5×28 / 4×6 深12
    返回 [{diameter, depth, raw}]
    """
    pairs = []
    seen_raw = set()

    # 模式B：数量×直径 深深度（先匹配，避免与模式A重复）
    for m in _QTY_DIA_DEPTH_PAT.finditer(text):
        qty = float(m.group(1))
        d = float(m.group(2))
        l = float(m.group(3)) if m.group(3) else 0.0
        if d > 0 and l > 0:
            raw = m.group(0).strip()
            if raw not in seen_raw:
                pairs.append({"diameter": d, "depth": l, "quantity": qty, "raw": raw})
                seen_raw.add(raw)

    # 模式A：[Ø]直径 深深度
    for m in _HOLE_DEPTH_PAT.finditer(text):
        d = float(m.group(1))
        l = float(m.group(2))
        if d > 0 and l > 0:
            raw = m.group(0).strip()
            if raw not in seen_raw:
                pairs.append({"diameter": d, "depth": l, "raw": raw})
                seen_raw.add(raw)
    return pairs


def parse_edge_distances(text: str) -> List[Dict[str, float]]:
    """
    解析边距与孔径配对（DFM-001）。返回 [{edge, diameter, raw}]。
    保守策略：只在边距标注同一行或相邻行存在可识别的孔径（Ø 显式或裸数字）时配对，
    无法可靠配对时跳过（No Evidence → No Finding，不猜测）。
    """
    edges = []
    lines = text.split("\n")
    for i, line in enumerate(lines):
        for m in _EDGE_RE.finditer(line):
            e = float(m.group(1))
            d = None
            # 在同一行及上下各一行窗口内找孔径
            window = lines[max(0, i - 1): min(len(lines), i + 2)]
            for wl in window:
                # 剔除行内边距标注段，避免把边距值自身误当孔径
                clean = _EDGE_RE.sub("", wl)
                dm = _DIA_RE.search(clean)
                if dm:
                    d = float(dm.group(1))
                    break
                # 数量×直径 模式：4×Ø6 / 4×6
                qd = re.search(
                    r'(\d+)\s*[×xX*]\s*(?:Ø|φ|Φ|DIA\.?|直径)?\s*(\d+(?:\.\d+)?)',
                    clean, re.IGNORECASE)
                if qd:
                    d = float(qd.group(2))
                    break
                # 裸孔径：行内含 孔/直径/钻 等语义词后的独立数字
                bare = re.search(
                    r'(?:孔|hole|直径|钻|DIA|Ø|φ)[^\d×]*(\d+(?:\.\d+)?)',
                    clean, re.IGNORECASE)
                if bare:
                    d = float(bare.group(1))
                    break
            if d and d > 0 and e > 0:
                edges.append({"edge": e, "diameter": d, "raw": m.group(0).strip()})
    return edges


_FCF_KW_RE = re.compile(
    r'(?:位置度|位置|位置度公差|同心度|垂直度|平行度|同轴度|圆跳动|全跳动|'
    r'POSITION|POS\.?|TRUE\s*POSITION|CONCENTRICITY|PERPENDICULARITY|'
    r'PARALLELISM|COAXIALITY|RUNOUT|PROFILE)',
    re.IGNORECASE)


def parse_fcf_datum_refs(text: str) -> List[Tuple[str, str]]:
    """
    从文本中提取特征控制框（FCF）的基准引用字母。
    返回 [(fcf片段, 基准字母串)]，如 [("位置度 | Ø0.10 | A | B | C", "ABC")]
    仅在 FCF 所在行内解析基准 token，避免误吞后续行的无关大写字母。
    """
    refs = []
    for m in _FCF_KW_RE.finditer(text):
        line_end = text.find("\n", m.start())
        line = text[m.start(): line_end if line_end != -1 else len(text)].strip()
        # 按 | 或空白拆分 token，取形如 A / B / A-B / [A] 的基准 token
        tokens = re.split(r"[|,，\s]+", line)
        datums = []
        for tok in tokens:
            tok = tok.strip()
            if re.fullmatch(r"[\[(]?[A-Za-z](?:[-–—/][A-Za-z])?[\])]?", tok):
                datums.append(re.sub(r"[\[\]()]", "", tok).upper())
        if datums:
            refs.append((line, "".join(datums)))
    return refs


# ── 确定性规则引擎 ────────────────────────────────────────────

class RuleEngine:
    """确定性规则执行器。接收启用规则列表，返回结构化 findings"""

    def __init__(self, enabled_rules: List[Dict[str, Any]]):
        self.enabled: Dict[str, Dict[str, Any]] = {}
        for r in enabled_rules:
            self.enabled[r["id"]] = r

    def run(self, extracted_text: str) -> List[IssueItem]:
        """
        执行全部可计算的确定性规则。
        文本类规则（DOC-001/REV-001/DOC-003/TOL-001）由 rule_checker.py 负责，
        此处只执行需要计算/解析的规则，避免重复报告。
        """
        if not extracted_text or not extracted_text.strip():
            return []
        findings: List[IssueItem] = []
        findings += self._gdt_001(extracted_text)
        findings += self._dfm_001(extracted_text)
        findings += self._dfm_002(extracted_text)
        return findings

    # ── GDT-001 被引用基准不存在（文本层最佳努力） ──────────────
    def _gdt_001(self, text: str) -> List[IssueItem]:
        rule = self.enabled.get("GDT-001")
        if not rule:
            return []
        refs = parse_fcf_datum_refs(text)
        if not refs:
            return []
        # 基准标签常见形态：单独字母 token（大写），或 "基准 A" / "DATUM A"
        findings = []
        for fcf, letters in refs:
            for ch in letters:
                defined = False
                if re.search(rf'(?:基准|DATUM|DATUM\s+FEATURE)[\s:]*{ch}\b', text, re.IGNORECASE):
                    defined = True
                # 单独成行的字母 token（图形基准符号的文本层）
                if re.search(rf'(?<![A-Za-z0-9]){ch}(?![A-Za-z0-9])', text):
                    defined = True
                if not defined:
                    findings.append(build_finding(
                        rule,
                        result="NEEDS_REVIEW",
                        title="被引用基准无法确认存在",
                        description=f"特征控制框引用了基准 {ch}，但文本层无法确认其定义。"
                                    f"（若基准符号为图形绘制，可能无法从文本提取，需人工复核。）",
                        evidence=[f"FCF: {fcf}", f"Referenced datum: {ch}"],
                        location="特征控制框",
                        confidence=0.6,
                        requires_human_review=True,
                        suggestion="人工确认基准 A/B/C 是否已在图纸上明确定义并关联到目标特征。",
                    ))
        return findings

    # ── DFM-001 孔边距风险 ─────────────────────────────────────
    def _dfm_001(self, text: str) -> List[IssueItem]:
        rule = self.enabled.get("DFM-001")
        if not rule:
            return []
        ratio = float(rule.get("parameters", {}).get("minimum_edge_distance_ratio", 1.0))
        findings = []
        for item in parse_edge_distances(text):
            e = item["edge"]
            d = item["diameter"]
            if d <= 0:
                continue
            calc_ratio = e / d
            if calc_ratio < ratio:
                findings.append(build_finding(
                    rule,
                    result="WARNING",
                    description=f"孔边距不足：E/D = {e:.1f}/{d:.1f} = {calc_ratio:.2f} < {ratio}",
                    evidence=[f"Edge distance E = {e} mm", f"Hole diameter D = {d} mm",
                              f"E/D = {calc_ratio:.2f}"],
                    calculation={"formula": "E / D", "value": round(calc_ratio, 3),
                                 "parameters": {"minimum_edge_distance_ratio": ratio}},
                    location="孔边距标注处",
                    location_feature=item["raw"],
                    engineering_risk="孔边距过小可能导致孔口破裂、变形或加工时材料坍塌。",
                    suggestion="增大孔边距或调整孔径，使 E/D ≥ 阈值；或按企业标准复核。",
                ))
        return findings

    # ── DFM-002 深孔风险 ───────────────────────────────────────
    def _dfm_002(self, text: str) -> List[IssueItem]:
        rule = self.enabled.get("DFM-002")
        if not rule:
            return []
        max_ratio = float(rule.get("parameters", {}).get("maximum_hole_depth_ratio", 5.0))
        findings = []
        for pair in parse_hole_pairs(text):
            d = pair["diameter"]
            l = pair["depth"]
            if d <= 0:
                continue
            calc_ratio = l / d
            if calc_ratio > max_ratio:
                findings.append(build_finding(
                    rule,
                    result="WARNING",
                    description=f"深孔风险：L/D = {l:.1f}/{d:.1f} = {calc_ratio:.2f} > {max_ratio}",
                    evidence=[f"Hole diameter = {d} mm", f"Hole depth = {l} mm",
                              f"L/D = {calc_ratio:.2f}"],
                    calculation={"formula": "L / D", "value": round(calc_ratio, 3),
                                 "parameters": {"maximum_hole_depth_ratio": max_ratio}},
                    location="深孔标注处",
                    location_feature=pair["raw"],
                    engineering_risk="深孔钻削排屑困难、钻头易偏斜/断裂，加工与检测成本显著上升。",
                    suggestion="复核深度是否为功能必需；评估是否可采用枪钻/深孔钻等工艺，或拆分结构。",
                ))
        return findings


# ── 统一入口：执行自定义正则规则（兼容旧 CUSTOM_RULE_CHECKS） ──
def run_custom_regex_checks(text: str) -> List[IssueItem]:
    """执行 custom_rules.py 的 CUSTOM_RULE_CHECKS（正则 must_exist / must_not_exist）"""
    if not CUSTOM_RULE_CHECKS:
        return []
    findings = []
    for rule in CUSTOM_RULE_CHECKS:
        try:
            pattern = rule.get("pattern", "")
            mode = rule.get("mode", "must_exist")
            matches = re.findall(pattern, text, re.IGNORECASE | re.MULTILINE)
            if mode == "must_exist" and not matches:
                findings.append(IssueItem(
                    id=f"custom_{rule.get('id', 'unknown')}",
                    category=rule.get("category", "custom"),
                    category_name=rule.get("name", "自定义规则"),
                    severity=Severity(rule.get("severity", "warning")),
                    title=rule.get("title", "自定义规则未通过"),
                    description=rule.get("description", ""),
                    suggestion=rule.get("suggestion", ""),
                    location=rule.get("location", "全文"),
                    source="rule",
                    rule_id=rule.get("id", "CUSTOM"),
                    rule_name=rule.get("name", ""),
                    finding_type="DOCUMENT_CONTROL",
                    standard_source=rule.get("standard_source", "CUSTOM"),
                ))
            elif mode == "must_not_exist" and matches:
                matched_text = matches[0] if matches else ""
                if isinstance(matched_text, tuple):
                    matched_text = " ".join(str(x) for x in matched_text if x)
                findings.append(IssueItem(
                    id=f"custom_{rule.get('id', 'unknown')}",
                    category=rule.get("category", "custom"),
                    category_name=rule.get("name", "自定义规则"),
                    severity=Severity(rule.get("severity", "warning")),
                    title=rule.get("title", "自定义规则未通过"),
                    description=f"{rule.get('description', '')} 匹配到: \"{str(matched_text)[:50]}\"",
                    suggestion=rule.get("suggestion", ""),
                    location=rule.get("location", "全文"),
                    source="rule",
                    rule_id=rule.get("id", "CUSTOM"),
                    rule_name=rule.get("name", ""),
                    finding_type="DOCUMENT_CONTROL",
                    standard_source=rule.get("standard_source", "CUSTOM"),
                ))
        except Exception as e:
            print(f"自定义规则 {rule.get('id', '?')} 执行出错: {e}")
    return findings
