"""
AI 审核引擎（Baseline V1.0 版）
- 分块多模态审核（全局图 + 标题栏 + 局部高清切片）
- 两轮 AI 审核：
    A. Hybrid 分块审核：逐块评估局部规则（DIM-001/002/003、TOL-001/003、GDT-002/003 等）
    B. AI 综合审核：跨视图/跨区域综合判断（DIM-004、TOL-004、GDT-004、MAT-003、DFM-005 等）
- 结构化 prompt + JSON 输出解析（rule_id / finding_type / evidence / calculation）
- 多模型兼容（OpenAI 格式，支持豆包/GPT/Claude）
- 重试与降级机制
"""
import json
import re
import asyncio
import time
import random
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass

import httpx

from config import (AI_CONFIG, DEFAULT_CHECKLIST, CUSTOM_TECH_REQS,
                    BASELINE_INSTRUCTION, SEVERITY_MAP, FINDING_TYPES,
                    FINDING_TYPE_LABEL_ZH, get_enabled_rules, EFFECTIVE_RULES)
from .models import IssueItem, Severity, CheckResult
from .pdf_processor import PDFChunk
from .rule_engine import build_finding


# ── 规则分类（两轮 AI 审核的划分） ────────────────────────────
# 局部规则：在单个视图/切片内即可评估
LOCAL_RULE_IDS = {
    "DOC-002", "DOC-003", "DIM-001", "DIM-002", "DIM-003",
    "TOL-001", "TOL-003", "GDT-002", "GDT-003",
    "MAT-001", "MAT-002", "MAT-004", "DFM-003", "DFM-004",
}
# 综合规则：需要跨视图/跨区域/结合全局上下文判断
COMPREHENSIVE_RULE_IDS = {
    "DIM-004", "DIM-005", "TOL-002", "TOL-004", "GDT-004",
    "MAT-003", "DFM-005", "DOC-004", "REV-002",
}


# ── Prompt 模板 ────────────────────────────────────────────────

def _build_system_prompt() -> str:
    """构建系统提示词（Baseline V1.0 + 自定义技术要求）"""
    base = BASELINE_INSTRUCTION

    if CUSTOM_TECH_REQS:
        custom_text = "\n\n【自定义审核依据 / Company Standards】\n"
        custom_text += "以下为必须遵守的额外审核标准（优先级高于 Baseline），请在审核时严格对照：\n"
        for i, req in enumerate(CUSTOM_TECH_REQS, 1):
            custom_text += f"{i}. {req}\n"
        base += custom_text

    base += """
\n【补充通用检查（无 Baseline 规则时作为总体观察）】
- 视图表达：主/俯/侧视图、剖视图、局部放大图是否充分表达结构。
- 制图规范：图层/线型/字体/符号是否清晰可读。
- 装配图专项：序号/BOM/配合代号/焊接符号是否完整。
若在切片中观察到上述方面的明显缺陷，可并入 overall_comment，不作为单独 finding。"""
    return base


SYSTEM_PROMPT = _build_system_prompt()


def _format_rule_block(rules: List[Dict]) -> str:
    """把规则列表格式化为 AI 可逐条执行的文本"""
    if not rules:
        return "（本轮无规则）"
    lines = []
    for r in rules:
        params = r.get("parameters") or {}
        param_str = ""
        if params:
            filled = {k: v for k, v in params.items() if v is not None}
            if filled:
                param_str = " | Parameters: " + ", ".join(f"{k}={v}" for k, v in filled.items())
        lines.append(f"- [{r['id']}] {r['name']} (Severity: {r['severity']}, "
                     f"finding_type: {r.get('finding_type', '')}){param_str}")
        lines.append(f"  Condition: {r.get('condition', '')}")
        lines.append(f"  Prompt: {r.get('prompt', '')}")
    return "\n".join(lines)


FINDING_TYPES_TEXT = "[" + ", ".join(FINDING_TYPES) + "]"

_OUTPUT_SCHEMA = """{
  "overall_comment": "对本张图纸/本轮的总体观察（50字以内）",
  "findings": [
    {
      "audit_standard": "Baseline V1.0",
      "rule_id": "触发的规则ID",
      "rule_name": "规则名称",
      "category": "规则大类",
      "result": "PASS/WARNING/CRITICAL/NEEDS_REVIEW/NOT_APPLICABLE",
      "severity": "规则定义严重度",
      "confidence": 0.0,
      "location": {"page": 0, "view": "视图/剖视/局部放大图", "feature": "特征标识"},
      "evidence": ["证据1", "证据2"],
      "parameters": {},
      "calculation": {"formula": "计算公式", "value": 0.0},
      "finding": "问题描述",
      "engineering_risk": "工程风险",
      "recommendation": "建议的工程复核/修改动作",
      "standard_source": "BASELINE",
      "requires_human_review": false,
      "finding_type": "DRAWING_ERROR"
    }
  ]
}"""


def build_audit_prompt(file_name: str, rules: List[Dict], precheck_info: Dict,
                       precheck_summary: str, chunk_desc: str,
                       mode: str = "local") -> str:
    """构建审核 prompt"""
    rule_block = _format_rule_block(rules)

    if mode == "local":
        mode_instruction = (
            "本轮为【分块审核】：请仅基于本切片中可见的视图/标注/特征，逐条评估下列规则。\n"
            "对于跨视图冲突或需要整张图纸上下文才能判断的规则，若本切片证据不足以判断，"
            "返回 NOT_APPLICABLE 或给出 NEEDS_REVIEW。"
        )
    else:
        mode_instruction = (
            "本轮为【跨视图综合审核】：请综合全部可见视图、剖视图、局部放大图、尺寸/公差/GD&T/"
            "材料/Notes/标题栏/修订表，进行跨区域、跨视图的关联判断。重点检查不同视图之间是否矛盾、"
            "组合制造风险是否显著上升。每条 finding 必须同时给出两处及以上冲突证据（若适用）。"
        )

    precheck_text = ""
    if precheck_info:
        precheck_text = "\n【规则前置检查已提取的标题栏信息】\n"
        for k, v in precheck_info.items():
            if v:
                precheck_text += f"- {k}: {v}\n"

    det_text = ""
    if precheck_summary:
        det_text = f"\n【确定性规则已发现的问题（不要再重复报告同一条规则同一条问题）】\n{precheck_summary}\n"

    return f"""请审核这张2D工程图纸：{file_name}

【图纸切片说明】
{chunk_desc}
{precheck_text}{det_text}
【本轮需执行的 Baseline 规则】
{rule_block}

【审核模式】
{mode_instruction}

【输出要求】
请严格按照以下 JSON 格式输出（不要输出 JSON 以外的任何内容）：
{_OUTPUT_SCHEMA}

规则说明：
- 只对 result 为 WARNING / CRITICAL / NEEDS_REVIEW 的规则输出 finding；
  PASS 和 NOT_APPLICABLE 一律不输出到 findings。
- EVIDENCE POLICY: No Evidence → No Finding。证据不足时 result 用 NEEDS_REVIEW，绝不猜测。
- severity 必须使用规则定义的严重度，不要自行改变。
- finding_type 只能从 {FINDING_TYPES_TEXT} 中选择。
- location 中 page 为页码（1 起），view 为视图/剖视/局部放大图名称，feature 为具体特征。
- 不要编造尺寸、公差、材料、基准、工艺、标准、版本或设计意图。
- 【公差规则重要边界】避空/让位/退刀槽/空刀/越程槽/非功能性尺寸（clearance, relief,
  undercut, 避空位）不需要单独标注公差，不应报告为 TOL-001/TOL-002 问题。
  判断避空/让位的典型特征：直径尺寸明显大于相邻的有公差配合直径（如φ37 > φ30配合面）、
  位于轴肩/台阶/端部、无公差标注、不参与配合或定位。只有配合、定位、密封、轴承、
  装配等功能性尺寸才需要关注公差是否充分。若无法判断尺寸是否为避空/让位，用 NEEDS_REVIEW。"""


# ── AI 客户端 ──────────────────────────────────────────────────

@dataclass
class AIModelConfig:
    base_url: str
    api_key: str
    model: str


class AIClient:
    """OpenAI 兼容接口的 AI 客户端（复用长连接 + 按错误类型重试）"""

    def __init__(self):
        self.primary = AIModelConfig(
            base_url=AI_CONFIG["base_url"],
            api_key=AI_CONFIG["api_key"],
            model=AI_CONFIG["model"],
        )
        self.fallback = None
        if AI_CONFIG.get("fallback_api_key"):
            self.fallback = AIModelConfig(
                base_url=AI_CONFIG["fallback_base_url"] or AI_CONFIG["base_url"],
                api_key=AI_CONFIG["fallback_api_key"],
                model=AI_CONFIG["fallback_model"] or AI_CONFIG["model"],
            )
        self.max_retries = AI_CONFIG["max_retries"]
        self.timeout = AI_CONFIG["timeout"]
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def is_configured(self) -> bool:
        return bool(self.primary.api_key)

    def _get_client(self) -> httpx.AsyncClient:
        """复用同一个 AsyncClient（长连接），避免每次请求重建连接池"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        """
        判断异常是否值得重试：
        - 可重试：超时 / 连接错误 / 网络错误 / 429 限流 / 5xx 服务端错误
        - 可重试：AI 返回内容为空或结构异常（偶发空响应，重试通常可恢复）
        - 不重试：400/401/403/404 等客户端错误
        """
        if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError,
                            httpx.NetworkError, httpx.TransportError)):
            return True
        if isinstance(exc, httpx.HTTPStatusError):
            return exc.response.status_code in (429, 500, 502, 503, 504)
        # AI 偶发返回空 content 或结构异常，重试可恢复
        if isinstance(exc, ValueError) and ("内容为空" in str(exc) or "结构异常" in str(exc) or "缺少" in str(exc)):
            return True
        return False

    async def _post_once(self, messages: List[Dict], config: AIModelConfig) -> str:
        """单次调用多模态接口，校验返回结构后返回 content 文本"""
        url = config.base_url.rstrip("/") + "/chat/completions"

        headers = {
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": config.model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": 4096,
        }

        client = self._get_client()
        resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise ValueError(f"AI 返回结构异常：缺少 choices[0].message.content（{e}）") from e
        if not isinstance(content, str) or not content.strip():
            raise ValueError("AI 返回内容为空")
        return content

    async def chat_with_images(self, messages: List[Dict],
                                config: Optional[AIModelConfig] = None) -> str:
        """调用多模态对话接口"""
        cfg = config or self.primary
        return await self._post_once(messages, cfg)

    async def audit_with_retry(self, messages: List[Dict]) -> str:
        """
        带重试和降级的审核调用。
        - 仅对可重试错误（超时/连接/429/5xx）重试，指数退避 + 随机抖动
        - 客户端错误（400/401/403 等）不重试
        - 主模型失败后降级到备用模型
        """
        last_error = None

        # 主模型
        for attempt in range(self.max_retries):
            try:
                return await self._post_once(messages, self.primary)
            except Exception as e:
                last_error = e
                if not self._is_retryable(e):
                    break  # 客户端/解析错误：不再重试
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(min(2 ** attempt, 15) + random.uniform(0, 1.0))

        # 降级到备用模型
        if self.fallback:
            for attempt in range(self.max_retries):
                try:
                    return await self._post_once(messages, self.fallback)
                except Exception as e:
                    last_error = e
                    if not self._is_retryable(e):
                        break
                    if attempt < self.max_retries - 1:
                        await asyncio.sleep(min(2 ** attempt, 15) + random.uniform(0, 1.0))

        raise RuntimeError(f"AI 审核调用失败（已重试主模型{self.max_retries}次"
                           f"{'，备用模型'+str(self.max_retries)+'次' if self.fallback else ''}）: {last_error}")


# ── 审核引擎 ───────────────────────────────────────────────────

class AIAuditor:
    """AI 审核引擎（Baseline V1.0）"""

    def __init__(self):
        self.client = AIClient()

    @property
    def demo_mode(self) -> bool:
        """是否为演示模式（未配置 API Key 时启用）"""
        return not self.client.is_configured

    def _rules_by_ids(self, enabled_rules: List[Dict], ids: set) -> List[Dict]:
        return [r for r in enabled_rules if r["id"] in ids]

    async def audit_file(self, file_name: str, chunks: List[PDFChunk],
                         enabled_rules: List[Dict],
                         precheck_info: Dict,
                         precheck_issues: List[IssueItem] = None,
                         progress_callback=None) -> Tuple[List[CheckResult], str]:
        """
        审核单个文件。
        流程（对应 10 步流水线的 ⑥⑦）：
        - ⑥ Hybrid 分块审核：逐块评估局部规则
        - ⑦ AI 综合审核：跨视图综合判断
        演示模式（无 API Key）：返回模拟审核数据。
        """
        # 演示模式
        if self.demo_mode:
            if progress_callback:
                await progress_callback("auditing", "演示模式：模拟 AI 审核中...")
            await asyncio.sleep(1.5)
            return self._generate_demo_results(file_name, enabled_rules, precheck_info)

        if not self.client.is_configured:
            raise RuntimeError("AI API Key 未配置，请设置环境变量 AI_API_KEY")

        local_rules = self._rules_by_ids(enabled_rules, LOCAL_RULE_IDS)
        comprehensive_rules = self._rules_by_ids(enabled_rules, COMPREHENSIVE_RULE_IDS)

        precheck_summary = "\n".join(
            f"- [{i.rule_id or i.category}] {i.title}" for i in (precheck_issues or [])
        ) or ""

        all_check_results: List[CheckResult] = []
        overall_comments = []
        ai_errors = []  # 记录 AI 审核阶段的错误（用于降级提示）

        async def _safe_audit(desc, chunks, rules, mode):
            """安全执行一组切片审核：失败时记录错误并继续，不中断整体流程"""
            try:
                return await self._audit_chunk_group(
                    file_name, chunks, rules, precheck_info,
                    precheck_summary, mode
                )
            except Exception as e:
                ai_errors.append(f"{desc}: {e}")
                return [], ""

        # ── ⑥ Hybrid 分块审核 ─────────────────────────────────
        global_chunks = [c for c in chunks if c.chunk_type in ("global", "title_block")]
        detail_chunks = [c for c in chunks if c.chunk_type == "detail"]

        if global_chunks and local_rules:
            if progress_callback:
                await progress_callback("auditing", "正在审核全局布局与标题栏（Hybrid 规则）...")
            results, comment = await _safe_audit(
                "全局/标题栏审核", global_chunks, local_rules, "local"
            )
            all_check_results.extend(results)
            if comment:
                overall_comments.append(comment)

        for i, chunk in enumerate(detail_chunks):
            if not local_rules:
                break
            if progress_callback:
                await progress_callback("auditing",
                                        f"正在审核局部区域 ({i+1}/{len(detail_chunks)})...")
            results, comment = await _safe_audit(
                f"局部区域{i+1}审核", [chunk], local_rules, "local"
            )
            all_check_results.extend(results)
            if comment:
                overall_comments.append(comment)

        # ── ⑦ AI 综合审核（跨视图） ───────────────────────────
        if comprehensive_rules and chunks:
            if progress_callback:
                await progress_callback("auditing", "正在跨视图综合审核（DIM-004/TOL-004/GDT-004/MAT-003/DFM-005 等）...")
            comp_chunks = [c for c in chunks if c.chunk_type in ("global", "title_block")]
            if not comp_chunks:
                comp_chunks = chunks
            results, comment = await _safe_audit(
                "跨视图综合审核", comp_chunks, comprehensive_rules, "comprehensive"
            )
            all_check_results.extend(results)
            if comment:
                overall_comments.append(comment)

        # 合并去重（⑨ 去重/冲突处理）
        merged = self._merge_check_results(all_check_results)

        # AI 部分失败时的降级提示（不阻断已检出的问题）
        if ai_errors:
            err_summary = "；".join(ai_errors[:2])
            overall_comments.append(
                f"⚠️ AI视觉审核部分失败（{len(ai_errors)}个阶段），已降级输出规则检查结果：{err_summary}"
            )

        overall_comment = "；".join(overall_comments[:3]) if overall_comments else ""

        return merged, overall_comment

    async def _audit_chunk_group(self, file_name: str, chunks: List[PDFChunk],
                                  rules: List[Dict],
                                  precheck_info: Dict,
                                  precheck_summary: str,
                                  mode: str) -> Tuple[List[CheckResult], str]:
        """审核一组切片"""
        chunk_desc = "\n".join([f"- [{c.chunk_type}] {c.description}" for c in chunks])

        user_prompt = build_audit_prompt(file_name, rules, precheck_info,
                                         precheck_summary, chunk_desc, mode)

        # 构建 messages
        content = [{"type": "text", "text": user_prompt}]
        for chunk in chunks:
            img_b64 = chunk.to_base64()
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}
            })

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ]

        raw_response = await self.client.audit_with_retry(messages)
        parsed = self._parse_response(raw_response)
        if not parsed:
            return [], ""

        findings = parsed.get("findings", [])
        rule_map = {r["id"]: r for r in rules}

        # ⑧ Evidence 验证 + 结构化转换
        issues = []
        for f_data in findings:
            rule_id = f_data.get("rule_id", "")
            rule = rule_map.get(rule_id)
            if not rule:
                continue
            issue = self._to_issue_item(f_data, rule)
            if issue:
                issues.append(issue)

        # 按大类分组为 CheckResult
        results = self._group_by_category(issues)
        return results, parsed.get("overall_comment", "")

    # ── 结构化转换 ────────────────────────────────────────────

    def _to_issue_item(self, data: Dict, rule: Dict) -> Optional[IssueItem]:
        """把 AI 返回的 finding 转为结构化 IssueItem，并做证据验证"""
        result = str(data.get("result", "")).upper()
        if result in ("PASS", "NOT_APPLICABLE", ""):
            return None

        # 证据验证：CRITICAL/WARNING 必须有证据，否则降级为 NEEDS_REVIEW
        evidence = data.get("evidence") or []
        requires_review = bool(data.get("requires_human_review", False))
        if result in ("CRITICAL", "WARNING") and not evidence:
            result = "NEEDS_REVIEW"
            requires_review = True

        severity_value = SEVERITY_MAP.get(rule.get("severity", "WARNING"), "warning")
        if result == "NEEDS_REVIEW":
            requires_review = True
            if severity_value == "block":
                severity_value = "warning"

        loc = data.get("location") or {}
        if isinstance(loc, dict):
            page = int(loc.get("page") or 0)
            view = str(loc.get("view") or "")
            feature = str(loc.get("feature") or "")
        else:
            page = int(data.get("page") or 0)
            view = ""
            feature = ""
        location = " · ".join(x for x in [
            f"第{page}页" if page else "",
            view,
            feature,
        ] if x)

        finding_type = data.get("finding_type", rule.get("finding_type", "DRAWING_ERROR"))
        if finding_type not in FINDING_TYPES:
            finding_type = rule.get("finding_type", "DRAWING_ERROR")

        # TOL-003 特殊：Cost / Manufacturability Risk
        if rule["id"] == "TOL-003":
            finding_type = "COST_RISK"

        confidence = float(data.get("confidence") or 1.0)
        try:
            confidence = max(0.0, min(1.0, confidence))
        except (TypeError, ValueError):
            confidence = 1.0

        return IssueItem(
            id=f"ai_{int(time.time()*1000)}_{abs(hash((rule['id'], location))) % 1_000_000:06d}",
            category=rule.get("category", ""),
            category_name=rule.get("category_name", ""),
            severity=Severity(severity_value),
            title=data.get("finding", rule.get("name_zh", rule.get("name", "")))[:80],
            description=data.get("finding", ""),
            location=location,
            suggestion=data.get("recommendation", ""),
            page=page,
            source="ai",
            rule_id=rule["id"],
            rule_name=rule.get("name", ""),
            finding_type=finding_type,
            result=result,
            confidence=confidence,
            evidence=[str(e) for e in evidence],
            parameters=dict(rule.get("parameters", {})),
            calculation=data.get("calculation") or {},
            engineering_risk=data.get("engineering_risk", ""),
            standard_source=data.get("standard_source", rule.get("standard_source", "BASELINE")),
            requires_human_review=requires_review,
            location_view=view,
            location_feature=feature,
        )

    @staticmethod
    def _group_by_category(issues: List[IssueItem]) -> List[CheckResult]:
        """按大类（DOC/DIM/TOL/GDT/MAT/DFM/REV）分组为 CheckResult"""
        groups: Dict[str, List[IssueItem]] = {}
        order = []
        for iss in issues:
            cid = iss.category or "OTHER"
            if cid not in groups:
                groups[cid] = []
                order.append(cid)
            groups[cid].append(iss)

        results = []
        for cid in order:
            iss_list = groups[cid]
            results.append(CheckResult(
                checklist_id=cid,
                checklist_name=iss_list[0].category_name or cid,
                passed=len(iss_list) == 0,
                issues=iss_list,
                note=f"发现 {len(iss_list)} 个问题" if iss_list else "未发现问题",
            ))
        return results

    @staticmethod
    def _parse_response(raw: str) -> Optional[Dict]:
        """解析 AI 返回的 JSON（处理可能的 markdown 包裹）"""
        text = raw.strip()
        if text.startswith("```"):
            text = re.sub(r'^```(?:json)?\s*', '', text)
            text = re.sub(r'\s*```$', '', text)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                try:
                    return json.loads(text[start:end + 1])
                except json.JSONDecodeError:
                    pass
        return None

    @staticmethod
    def _merge_check_results(results: List[CheckResult]) -> List[CheckResult]:
        """合并多次审核的结果，按 category 去重"""
        merged: Dict[str, CheckResult] = {}

        for cr in results:
            cid = cr.checklist_id or cr.checklist_name
            if cid not in merged:
                merged[cid] = CheckResult(
                    checklist_id=cr.checklist_id,
                    checklist_name=cr.checklist_name,
                    passed=cr.passed,
                    issues=list(cr.issues),
                    note=cr.note,
                )
            else:
                existing = merged[cid]
                existing.passed = existing.passed and cr.passed
                # 去重（按 rule_id + location）
                seen = {(i.rule_id, i.location, i.finding_type) for i in existing.issues}
                for iss in cr.issues:
                    key = (iss.rule_id, iss.location, iss.finding_type)
                    if key not in seen:
                        existing.issues.append(iss)
                        seen.add(key)
                if cr.note and cr.note not in existing.note:
                    existing.note = (existing.note + "；" + cr.note).strip("；")

        return list(merged.values())

    # ── 演示模式 ──────────────────────────────────────────────

    def _generate_demo_results(self, file_name: str, enabled_rules: List[Dict],
                                precheck_info: Dict) -> Tuple[List[CheckResult], str]:
        """演示模式：基于规则生成结构化模拟数据"""
        import hashlib
        seed = int(hashlib.md5(file_name.encode()).hexdigest()[:8], 16)

        demo_findings = [
            # (rule_id, result, finding, evidence, calc, risk, suggestion)
            ("DIM-001", "CRITICAL", "主视图中某加工特征尺寸不完整",
             ["Feature: Hole H2", "Size callout: Ø8"], None,
             "加工时无法唯一确定特征尺寸。", "补全该特征的尺寸/深度/位置标注。"),
            ("DIM-003", "WARNING", "存在封闭尺寸链",
             ["A-B = 30", "B-C = 20", "A-C = 50"], {"formula": "30+20=50", "value": 50},
             "公差累积影响配合。", "删除其中一个非关键尺寸或改为参考尺寸。"),
            ("DIM-004", "CRITICAL", "跨视图特征数量冲突",
             ["Front View: 4×Ø6", "Detail A: 6×Ø6"], None,
             "同一特征在不同视图数量不一致。", "统一各视图中的孔数量。"),
            ("TOL-003", "WARNING", "公差相对特征尺寸过严，成本风险高",
             ["Ø12 ±0.005", "Process: turning"], {"formula": "tolerance/feature", "value": 0.0004},
             "过严公差显著推高加工与检测成本。", "复核公差是否功能必需，必要时放宽。"),
            ("DFM-002", "WARNING", "深孔风险：L/D 超阈值",
             ["Hole diameter = 3 mm", "Hole depth = 22 mm"],
             {"formula": "L / D", "value": 7.33},
             "深孔钻削排屑困难。", "复核深度是否功能必需，评估专用深孔工艺。"),
            ("MAT-001", "CRITICAL", "材料牌号存在歧义",
             ["Material: 不锈钢"], None,
             "不锈钢牌号众多，无法唯一确定。", "写明具体牌号，如 304、316L。"),
            ("GDT-004", "WARNING", "位置度缺少基本尺寸支撑",
             ["FCF: POSITION Ø0.1 A B C", "No basic dimensions"], None,
             "位置度无法唯一约束。", "补充基本尺寸或基准体系。"),
            ("REV-002", "CRITICAL", "修订表与当前版本冲突",
             ["Title block: Rev B", "Revision table latest: Rev C"], None,
             "版本标识矛盾。", "统一标题栏与修订表版本。"),
        ]

        issues = []
        for i, (rid, result, finding, ev, calc, risk, sug) in enumerate(demo_findings):
            if (seed >> (i * 3)) % 5 == 0:
                continue  # 随机略过部分问题
            rule = next((r for r in enabled_rules if r["id"] == rid), None)
            if not rule:
                continue
            # 确定性规则由规则引擎计算，演示数据不重复生成
            if rule.get("execution") == "Deterministic":
                continue
            severity_value = SEVERITY_MAP.get(rule.get("severity", "WARNING"), "warning")
            issues.append(IssueItem(
                id=f"demo_{rid}_{i}",
                category=rule.get("category", ""),
                category_name=rule.get("category_name", ""),
                severity=Severity(severity_value),
                title=finding,
                description=finding,
                location="主视图",
                suggestion=sug,
                page=0,
                source="ai",
                rule_id=rid,
                rule_name=rule.get("name", ""),
                finding_type=rule.get("finding_type", "DRAWING_ERROR"),
                result=result,
                confidence=0.9,
                evidence=list(ev),
                parameters=dict(rule.get("parameters", {})),
                calculation=calc or {},
                engineering_risk=risk,
                standard_source=rule.get("standard_source", "BASELINE"),
                requires_human_review=False,
            ))

        results = self._group_by_category(issues)
        block_count = sum(1 for i in issues if i.severity == Severity.BLOCK)
        if block_count:
            comment = f"发现 {block_count} 个阻断级问题，需修改后复审。（演示模式模拟数据）"
        elif issues:
            comment = f"发现 {len(issues)} 个待改进项，建议优化后发布。（演示模式模拟数据）"
        else:
            comment = "图纸审核通过，未发现明显问题。（演示模式模拟数据）"
        return results, comment
