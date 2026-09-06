"""
报告生成模块
- 单张图纸：Markdown 审核报告 + JSON 数据文件
- 批量审核：汇总报告
- 回写到原文件夹
"""
import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any

from .models import (FileAuditResult, BatchAuditResult, IssueItem,
                     Severity, CheckResult, AuditStatus)
from config import SEVERITY_LEVELS


SEVERITY_EMOJI = {
    Severity.BLOCK: "🔴",
    Severity.WARNING: "🟡",
    Severity.INFO: "🔵",
}

SEVERITY_LABEL = {
    Severity.BLOCK: "阻断级",
    Severity.WARNING: "警告级",
    Severity.INFO: "建议级",
}


class ReportWriter:
    """报告生成器"""

    @staticmethod
    def write_file_report(result: FileAuditResult) -> FileAuditResult:
        """
        为单张图纸生成报告，回写到原 PDF 同目录。
        生成：<文件名>_审核报告.md 和 <文件名>_audit_result.json
        """
        pdf_path = Path(result.file_path)
        base_name = pdf_path.stem
        output_dir = pdf_path.parent

        # Markdown 报告
        md_path = output_dir / f"{base_name}_审核报告.md"
        md_content = ReportWriter._generate_markdown(result)
        md_path.write_text(md_content, encoding="utf-8")
        result.report_md_path = str(md_path)

        # JSON 数据文件
        json_path = output_dir / f"{base_name}_audit_result.json"
        json_content = result.model_dump_json(indent=2, exclude={"thumbnail"})
        json_path.write_text(json_content, encoding="utf-8")
        result.report_json_path = str(json_path)

        return result

    @staticmethod
    def write_batch_summary(batch: BatchAuditResult) -> BatchAuditResult:
        """生成批量审核汇总报告"""
        folder = Path(batch.folder_path)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        summary_path = folder / f"_审核汇总_{timestamp}.md"

        content = ReportWriter._generate_batch_summary(batch)
        summary_path.write_text(content, encoding="utf-8")
        batch.summary_report_path = str(summary_path)

        # 同时保存批量 JSON
        batch_json_path = folder / f"_audit_batch_{timestamp}.json"
        batch_json_path.write_text(
            batch.model_dump_json(indent=2, exclude={"files": {"__all__": {"thumbnail"}}}),
            encoding="utf-8"
        )

        return batch

    # ── Markdown 生成 ───────────────────────────────────────────

    @staticmethod
    def _generate_markdown(result: FileAuditResult) -> str:
        """生成单张图纸的 Markdown 报告"""
        lines = []

        # 标题
        status_icon = "✅" if result.passed else "❌"
        lines.append(f"# {status_icon} 图纸审核报告：{result.file_name}")
        lines.append("")
        lines.append(f"**审核标准**：{result.audit_standard or 'Baseline V1.0'}  ")
        lines.append(f"**审核时间**：{result.completed_at or datetime.now().isoformat()}  ")
        lines.append(f"**文件路径**：`{result.file_path}`  ")
        lines.append(f"**页数**：{result.page_count}  ")
        lines.append(f"**审核耗时**：{result.duration_seconds:.1f} 秒  ")
        lines.append("")

        # 审核结论
        lines.append("## 📊 审核结论")
        lines.append("")
        if result.passed:
            lines.append("> **通过** — 未发现阻断级问题，可进入下一环节。")
        else:
            lines.append(f"> **不通过** — 发现 {result.block_count} 个阻断级问题，"
                         f"{result.warning_count} 个警告级问题，需修改后复审。")
        lines.append("")

        if result.overall_comment:
            lines.append(f"**总体评价**：{result.overall_comment}")
            lines.append("")

        # 问题统计
        lines.append("## 📈 问题统计")
        lines.append("")
        lines.append("| 严重等级 | 数量 |")
        lines.append("|---------|------|")
        lines.append(f"| 🔴 阻断级 | {result.block_count} |")
        lines.append(f"| 🟡 警告级 | {result.warning_count} |")
        lines.append(f"| 🔵 建议级 | {result.info_count} |")
        lines.append(f"| **合计** | **{result.total_issues}** |")
        lines.append("")

        # 标题栏信息
        if result.title_block_info:
            lines.append("## 🏷️ 标题栏信息（规则提取）")
            lines.append("")
            label_map = {
                "drawing_number": "图号/物料编码",
                "revision": "版本号",
                "title": "图名",
                "material": "材料",
                "scale": "比例",
                "date": "出图日期",
            }
            for key, label in label_map.items():
                val = result.title_block_info.get(key, "")
                if val:
                    lines.append(f"- **{label}**：{val}")
            lines.append("")

        # 规则前置检查问题
        rule_issues = [i for i in result.precheck_issues if i.source == "rule"]
        if rule_issues:
            lines.append("## ⚙️ 规则前置检查发现的问题")
            lines.append("")
            for i, issue in enumerate(rule_issues, 1):
                lines.extend(ReportWriter._format_issue(i, issue))
            lines.append("")

        # 确定性规则计算结果
        if result.deterministic_issues:
            lines.append("## 🧮 确定性规则计算结果（DFM-001/002、GDT-001 等）")
            lines.append("")
            for i, issue in enumerate(result.deterministic_issues, 1):
                lines.extend(ReportWriter._format_issue(i, issue))
            lines.append("")

        # AI 审核详细结果
        lines.append("## 🔍 AI 审核详细结果")
        lines.append("")

        for cr in result.check_results:
            status = "✅ 通过" if cr.passed else "❌ 不通过"
            lines.append(f"### {cr.checklist_name} — {status}")
            lines.append("")
            if cr.note:
                lines.append(f"> {cr.note}")
                lines.append("")
            if cr.issues:
                for i, issue in enumerate(cr.issues, 1):
                    lines.extend(ReportWriter._format_issue(i, issue))
            else:
                lines.append("未发现问题。")
            lines.append("")

        # 所有问题汇总表
        all_issues = result.precheck_issues + result.deterministic_issues + result.ai_issues
        if all_issues:
            lines.append("## 📋 问题清单汇总")
            lines.append("")
            lines.append("| 序号 | 等级 | 规则 | 类型 | 检查项 | 问题 | 位置 | 建议 |")
            lines.append("|------|------|------|------|--------|------|------|------|")
            for i, issue in enumerate(all_issues, 1):
                sev = SEVERITY_EMOJI.get(issue.severity, "⚪")
                rid = issue.rule_id or "-"
                ft = ReportWriter._finding_type_zh(issue.finding_type) if issue.finding_type else "-"
                title = issue.title.replace("|", "\\|")[:24]
                loc = issue.location.replace("|", "\\|")[:18]
                sug = issue.suggestion.replace("|", "\\|")[:36]
                lines.append(f"| {i} | {sev} | {rid} | {ft} | {issue.category_name} | {title} | {loc} | {sug} |")
            lines.append("")

        # 页脚
        lines.append("---")
        lines.append(f"*本报告由 2D图纸审核高手 自动生成于 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")

        return "\n".join(lines)

    @staticmethod
    def _format_issue(index: int, issue: IssueItem) -> List[str]:
        """格式化单条问题（含 Baseline 结构化字段）"""
        sev = SEVERITY_EMOJI.get(issue.severity, "⚪")
        sev_label = SEVERITY_LABEL.get(issue.severity, "未知")
        lines = [
            f"**{index}. {sev} [{sev_label}] {issue.title}**",
            "",
        ]
        meta = []
        if issue.rule_id:
            meta.append(f"规则 `{issue.rule_id}`")
        if issue.finding_type:
            ft = ReportWriter._finding_type_zh(issue.finding_type)
            meta.append(f"类型：{ft}（{issue.finding_type}）")
        if issue.standard_source:
            meta.append(f"来源：{issue.standard_source}")
        if issue.result:
            meta.append(f"结果：{issue.result}")
        if issue.requires_human_review:
            meta.append("⚠️ 需人工复核")
        if meta:
            lines.append(f"- **规则信息**：{' | '.join(meta)}")
        if issue.description:
            lines.append(f"- **问题描述**：{issue.description}")
        if issue.location:
            lines.append(f"- **位置**：{issue.location}")
        if issue.evidence:
            lines.append(f"- **证据**：{'；'.join(str(e) for e in issue.evidence)}")
        if issue.calculation:
            calc = issue.calculation
            parts = []
            if calc.get("formula"):
                parts.append(f"{calc['formula']} = {calc.get('value', '')}")
            for k, v in calc.items():
                if k not in ("formula", "value"):
                    parts.append(f"{k}={v}")
            if parts:
                lines.append(f"- **计算**：{'；'.join(parts)}")
        if issue.engineering_risk:
            lines.append(f"- **工程风险**：{issue.engineering_risk}")
        if issue.suggestion:
            lines.append(f"- **修改建议**：{issue.suggestion}")
        lines.append("")
        return lines

    @staticmethod
    def _finding_type_zh(ft: str) -> str:
        return {
            "DRAWING_ERROR": "图纸错误",
            "AMBIGUITY": "信息歧义",
            "MANUFACTURING_RISK": "可制造性风险",
            "COST_RISK": "成本风险",
            "INSPECTION_RISK": "检测风险",
            "DOCUMENT_CONTROL": "文件控制",
        }.get(ft, ft)

    @staticmethod
    def _generate_batch_summary(batch: BatchAuditResult) -> str:
        """生成批量审核汇总报告"""
        lines = []

        lines.append(f"# 📦 批量图纸审核汇总：{batch.folder_name}")
        lines.append("")
        lines.append(f"**审核时间**：{batch.completed_at or datetime.now().isoformat()}  ")
        lines.append(f"**文件夹**：`{batch.folder_path}`  ")
        lines.append(f"**图纸总数**：{batch.total_files}  ")
        lines.append(f"**完成**：{batch.completed_files} / **失败**：{batch.failed_files}  ")
        lines.append(f"**通过率**：{batch.pass_rate:.1f}%  ")
        lines.append("")

        # 总体统计
        lines.append("## 📊 总体问题统计")
        lines.append("")
        lines.append("| 严重等级 | 数量 |")
        lines.append("|---------|------|")
        lines.append(f"| 🔴 阻断级 | {batch.block_count} |")
        lines.append(f"| 🟡 警告级 | {batch.warning_count} |")
        lines.append(f"| 🔵 建议级 | {batch.info_count} |")
        lines.append(f"| **合计** | **{batch.total_issues}** |")
        lines.append("")

        # 逐张结果表
        lines.append("## 📋 逐张审核结果")
        lines.append("")
        lines.append("| 序号 | 文件名 | 状态 | 阻断 | 警告 | 建议 | 结论 |")
        lines.append("|------|--------|------|------|------|------|------|")
        for i, f in enumerate(batch.files, 1):
            status = "✅" if f.passed else "❌"
            if f.status == AuditStatus.FAILED:
                status = "⚠️"
            conclusion = "通过" if f.passed else "不通过"
            if f.status == AuditStatus.FAILED:
                conclusion = "审核失败"
            lines.append(
                f"| {i} | {f.file_name} | {status} | "
                f"{f.block_count} | {f.warning_count} | {f.info_count} | {conclusion} |"
            )
        lines.append("")

        # 阻断级问题汇总
        all_block_issues = []
        for f in batch.files:
            for issue in f.precheck_issues + f.deterministic_issues + f.ai_issues:
                if issue.severity == Severity.BLOCK:
                    all_block_issues.append((f.file_name, issue))

        if all_block_issues:
            lines.append("## 🔴 阻断级问题汇总（必须修改）")
            lines.append("")
            for i, (fname, issue) in enumerate(all_block_issues, 1):
                rule_tag = f" [{issue.rule_id}]" if issue.rule_id else ""
                ft = ReportWriter._finding_type_zh(issue.finding_type) if issue.finding_type else ""
                type_tag = f"（{ft}）" if ft else ""
                lines.append(f"**{i}. [{fname}]{rule_tag}{type_tag} {issue.title}**")
                if issue.description:
                    lines.append(f"- 描述：{issue.description}")
                if issue.location:
                    lines.append(f"- 位置：{issue.location}")
                if issue.evidence:
                    lines.append(f"- 证据：{'；'.join(str(e) for e in issue.evidence)}")
                if issue.suggestion:
                    lines.append(f"- 建议：{issue.suggestion}")
                lines.append("")

        # 页脚
        lines.append("---")
        lines.append(f"*本汇总由 2D图纸审核高手 自动生成于 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")

        return "\n".join(lines)
