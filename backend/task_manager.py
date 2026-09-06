"""
任务管理模块
- 批量审核任务的创建、执行、状态管理
- SQLite 历史记录存储
- 并发控制与进度回调
"""
import asyncio
import re
import sqlite3
import time
import unicodedata
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable, Awaitable

from config import (DB_PATH, AUDIT_CONFIG, AI_CONFIG, DEFAULT_CHECKLIST,
                    get_enabled_rules, EFFECTIVE_RULES)
from .models import (BatchAuditResult, FileAuditResult, AuditStatus,
                     Severity, IssueItem)
from .pdf_processor import PDFProcessor, scan_pdf_folder, PDFOpenError
from .rule_checker import RuleChecker
from .rule_engine import RuleEngine, run_custom_regex_checks
from .ai_auditor import AIAuditor
from .report_writer import ReportWriter


ProgressCallback = Callable[[str, str, Optional[Dict]], Awaitable[None]]


class TaskManager:
    """审核任务管理器"""

    def __init__(self):
        self._init_db()
        self.ai_auditor = AIAuditor()
        self._active_tasks: Dict[str, BatchAuditResult] = {}
        self._task_locks: Dict[str, asyncio.Lock] = {}

    # ── 数据库 ──────────────────────────────────────────────────

    def _init_db(self):
        """初始化 SQLite 数据库（含旧库迁移：补列 + audit_files 重建唯一约束）"""
        conn = sqlite3.connect(str(DB_PATH))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_tasks (
                task_id TEXT PRIMARY KEY,
                folder_path TEXT NOT NULL,
                folder_name TEXT,
                status TEXT DEFAULT 'pending',
                created_at TEXT,
                completed_at TEXT,
                total_files INTEGER DEFAULT 0,
                completed_files INTEGER DEFAULT 0,
                failed_files INTEGER DEFAULT 0,
                total_issues INTEGER DEFAULT 0,
                block_count INTEGER DEFAULT 0,
                warning_count INTEGER DEFAULT 0,
                info_count INTEGER DEFAULT 0,
                pass_rate REAL DEFAULT 0,
                summary_report_path TEXT,
                audit_standard TEXT DEFAULT 'Baseline V1.0',
                model_version TEXT DEFAULT '',
                rules_version TEXT DEFAULT 'Baseline V1.0',
                error TEXT DEFAULT ''
            )
        """)
        # 旧 audit_tasks 表补列（非破坏性）
        _cols = {r[1] for r in conn.execute("PRAGMA table_info(audit_tasks)").fetchall()}
        for _c, _ddl in {
            "audit_standard": "TEXT DEFAULT 'Baseline V1.0'",
            "model_version": "TEXT DEFAULT ''",
            "rules_version": "TEXT DEFAULT 'Baseline V1.0'",
            "error": "TEXT DEFAULT ''",
        }.items():
            if _c not in _cols:
                conn.execute(f"ALTER TABLE audit_tasks ADD COLUMN {_c} {_ddl}")

        # audit_files：需要 UNIQUE(task_id, file_path) + audit_json 等新列 → 重建迁移
        self._migrate_audit_files(conn)
        conn.commit()
        conn.close()

    @staticmethod
    def _migrate_audit_files(conn):
        """确保 audit_files 具备 UNIQUE(task_id, file_path) 与完整详情列。
        旧表无唯一约束会产生重复行，这里统一重建（每 任务+文件 保留最新一条）。"""
        def _has_target_unique():
            for idx in conn.execute("PRAGMA index_list(audit_files)").fetchall():
                if idx[2] != 1:  # 'unique' 标志
                    continue
                cols = [r[2] for r in conn.execute(
                    f"PRAGMA index_info({idx[1]})").fetchall()]
                if sorted(cols) == ["file_path", "task_id"]:
                    return True
            return False

        _cols = {r[1] for r in conn.execute("PRAGMA table_info(audit_files)").fetchall()}
        _has_new_cols = all(c in _cols for c in
                            ("audit_json", "rules_version", "model_version", "error"))
        if _has_new_cols and _has_target_unique():
            return  # 已是最新 schema

        conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_files_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT,
                file_path TEXT,
                file_name TEXT,
                status TEXT DEFAULT 'pending',
                total_issues INTEGER DEFAULT 0,
                block_count INTEGER DEFAULT 0,
                warning_count INTEGER DEFAULT 0,
                info_count INTEGER DEFAULT 0,
                passed INTEGER DEFAULT 1,
                report_md_path TEXT,
                report_json_path TEXT,
                audit_json TEXT,
                rules_version TEXT DEFAULT 'Baseline V1.0',
                model_version TEXT DEFAULT '',
                error TEXT DEFAULT '',
                UNIQUE(task_id, file_path),
                FOREIGN KEY (task_id) REFERENCES audit_tasks(task_id)
            )
        """)
        # 从旧表迁移（保留 任务+文件 的最新记录）
        _old = conn.execute("PRAGMA table_info(audit_files)").fetchall()
        if _old:
            _old_cols = {r[1] for r in _old}
            _common = [c for c in
                       ("task_id", "file_path", "file_name", "status", "total_issues",
                        "block_count", "warning_count", "info_count", "passed",
                        "report_md_path", "report_json_path", "audit_json",
                        "rules_version", "model_version", "error")
                       if c in _old_cols]
            if _common:
                _sel = ", ".join(_common)
                conn.execute(
                    f"INSERT OR REPLACE INTO audit_files_new ({_sel}) "
                    f"SELECT {_sel} FROM audit_files ORDER BY id"
                )
            conn.execute("DROP TABLE audit_files")
        conn.execute("ALTER TABLE audit_files_new RENAME TO audit_files")

    def _save_task_to_db(self, batch: BatchAuditResult):
        """保存/更新任务到数据库（audit_files 按 任务+文件 唯一约束 UPSERT）"""
        conn = sqlite3.connect(str(DB_PATH))
        conn.execute("""
            INSERT OR REPLACE INTO audit_tasks
            (task_id, folder_path, folder_name, status, created_at, completed_at,
             total_files, completed_files, failed_files,
             total_issues, block_count, warning_count, info_count,
             pass_rate, summary_report_path, audit_standard, model_version,
             rules_version, error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            batch.task_id, batch.folder_path, batch.folder_name,
            batch.status.value, batch.created_at, batch.completed_at,
            batch.total_files, batch.completed_files, batch.failed_files,
            batch.total_issues, batch.block_count, batch.warning_count,
            batch.info_count, batch.pass_rate, batch.summary_report_path,
            getattr(batch, "audit_standard", "Baseline V1.0") or "Baseline V1.0",
            getattr(batch, "model_version", "") or "",
            getattr(batch, "rules_version", "Baseline V1.0") or "Baseline V1.0",
            getattr(batch, "error", "") or "",
        ))

        # 保存文件记录（按 task_id+file_path 唯一约束 UPSERT，不再产生重复行）
        for f in batch.files:
            self._upsert_file(conn, batch.task_id, f)
        conn.commit()
        conn.close()

    @staticmethod
    def _upsert_file(conn, task_id: str, f: FileAuditResult):
        """单文件 UPSERT（audit_json 存完整结构化详情，用于重启后恢复）"""
        audit_json = f.model_dump_json(exclude={
            "thumbnail", "extracted_text", "title_block_text"
        })
        conn.execute("""
            INSERT INTO audit_files
            (task_id, file_path, file_name, status, total_issues,
             block_count, warning_count, info_count, passed,
             report_md_path, report_json_path, audit_json,
             rules_version, model_version, error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(task_id, file_path) DO UPDATE SET
              file_name=excluded.file_name,
              status=excluded.status,
              total_issues=excluded.total_issues,
              block_count=excluded.block_count,
              warning_count=excluded.warning_count,
              info_count=excluded.info_count,
              passed=excluded.passed,
              report_md_path=excluded.report_md_path,
              report_json_path=excluded.report_json_path,
              audit_json=excluded.audit_json,
              rules_version=excluded.rules_version,
              model_version=excluded.model_version,
              error=excluded.error
        """, (
            task_id, f.file_path, f.file_name, f.status.value,
            f.total_issues, f.block_count, f.warning_count, f.info_count,
            1 if f.passed else 0, f.report_md_path, f.report_json_path,
            audit_json,
            f.rules_version or "Baseline V1.0",
            f.model_version or "",
            f.error or "",
        ))

    def _save_file_to_db(self, task_id: str, f: FileAuditResult):
        """保存单个文件的审核记录（每张图纸完成后调用，重启可恢复进度）"""
        try:
            conn = sqlite3.connect(str(DB_PATH))
            self._upsert_file(conn, task_id, f)
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"保存文件记录失败 {f.file_name}: {e}")

    def get_task_history(self, limit: int = 50) -> List[Dict]:
        """获取历史任务列表"""
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM audit_tasks ORDER BY created_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_task_files(self, task_id: str) -> List[Dict]:
        """获取任务的文件记录"""
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM audit_files WHERE task_id = ? ORDER BY file_name",
            (task_id,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def restore_task_from_db(self, task_id: str) -> Optional[BatchAuditResult]:
        """
        从数据库重建完整任务详情（服务重启后恢复已完成/部分完成任务的审核详情）。
        优先使用每张图纸持久化的 audit_json（含全部问题/证据/规则版本），
        无详情时回退为简化文件记录。
        """
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT * FROM audit_tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if not row:
                return None
            rows = conn.execute(
                "SELECT * FROM audit_files WHERE task_id = ? ORDER BY file_name",
                (task_id,)
            ).fetchall()

            try:
                status = AuditStatus(row["status"])
            except Exception:
                status = AuditStatus.COMPLETED

            batch = BatchAuditResult(
                task_id=row["task_id"],
                folder_path=row["folder_path"],
                folder_name=row["folder_name"] or "",
                status=status,
                created_at=row["created_at"] or "",
                completed_at=row["completed_at"],
                total_files=row["total_files"] or 0,
                completed_files=row["completed_files"] or 0,
                failed_files=row["failed_files"] or 0,
                total_issues=row["total_issues"] or 0,
                block_count=row["block_count"] or 0,
                warning_count=row["warning_count"] or 0,
                info_count=row["info_count"] or 0,
                pass_rate=row["pass_rate"] or 0.0,
                summary_report_path=row["summary_report_path"] or "",
                audit_standard=row["audit_standard"] or "Baseline V1.0",
                model_version=row["model_version"] or "",
                rules_version=row["rules_version"] or "Baseline V1.0",
                error=row["error"] or "",
            )

            for fr in rows:
                try:
                    if fr["audit_json"]:
                        file_result = FileAuditResult.model_validate_json(fr["audit_json"])
                    else:
                        # 旧记录无详情：重建简化对象
                        file_result = FileAuditResult(
                            file_path=fr["file_path"],
                            file_name=fr["file_name"] or Path(fr["file_path"]).name,
                        )
                        try:
                            file_result.status = AuditStatus(fr["status"])
                        except Exception:
                            pass
                        file_result.total_issues = fr["total_issues"] or 0
                        file_result.block_count = fr["block_count"] or 0
                        file_result.warning_count = fr["warning_count"] or 0
                        file_result.info_count = fr["info_count"] or 0
                        file_result.passed = bool(fr["passed"])
                        file_result.report_md_path = fr["report_md_path"] or ""
                        file_result.report_json_path = fr["report_json_path"] or ""
                    batch.files.append(file_result)
                except Exception:
                    continue
            return batch
        finally:
            conn.close()

    # ── 任务创建与执行 ───────────────────────────────────────────

    @staticmethod
    def _sanitize_path(p: str) -> str:
        """清理用户输入的路径：去掉首尾空白与全部不可见格式字符（零宽空格/BOM/双向控制符等）"""
        if not p:
            return p
        p = p.strip()
        # 移除所有 Unicode 格式类字符（Cf）：零宽空格、零宽连接符、BOM、双向控制符等
        p = "".join(ch for ch in p if unicodedata.category(ch) != "Cf")
        return p.strip()

    @staticmethod
    def _extract_path(p: str) -> Optional[str]:
        """从输入文本中提取真正的文件夹路径（兼容输入里混入说明文字，如 'D:\\图纸 请审核'）"""
        if not p:
            return None
        p = p.strip().strip('"').strip("'")
        # 路径结束符：空白 + ASCII 特殊字符 + 中英文标点（不含中括号，避免破坏字符类）
        term = r'\s"\'<>|?*，。、！？；：,;!?（）()'
        # Windows 绝对路径（盘符: 开头）
        m = re.search(r"[A-Za-z]:[\\/][^" + term + r"]+", p)
        if m:
            return m.group(0).rstrip("\\/")
        # UNC 路径 \\server\share\...
        m = re.search(r"\\\\[^" + term + r"]+", p)
        if m:
            return m.group(0).rstrip("\\/")
        return p.rstrip("\\/")

    def create_task(self, folder_path: str,
                     checklist_ids: Optional[List[str]] = None,
                     recursive: bool = True,
                     folder_name: Optional[str] = None) -> BatchAuditResult:
        """创建审核任务（扫描文件，不执行审核）"""
        folder_path = self._sanitize_path(folder_path)
        folder = Path(folder_path)
        if not folder.exists():
            # 兜底：尝试从输入文本中提取真正的路径（如 "D:\图纸 请审核"）
            extracted = self._extract_path(folder_path)
            if extracted and extracted != folder_path and Path(extracted).exists():
                folder_path = extracted
                folder = Path(extracted)
        if not folder.exists():
            raise FileNotFoundError(f"文件夹不存在: {folder_path}")

        pdf_files = scan_pdf_folder(folder_path, recursive=recursive)
        if not pdf_files:
            raise ValueError(f"文件夹中未找到 PDF 文件: {folder_path}")

        # 限制：每次最多审核 10 张
        MAX_FILES = 10
        if len(pdf_files) > MAX_FILES:
            raise ValueError(f"文件夹中包含 {len(pdf_files)} 张 PDF，超过每次最多 {MAX_FILES} 张的限制。请分批审核。")

        task_id = str(uuid.uuid4())[:8]
        now = datetime.now().isoformat()

        # 确定 checklist
        if checklist_ids:
            checklist = [c for c in DEFAULT_CHECKLIST if c["id"] in checklist_ids]
        else:
            checklist = [c for c in DEFAULT_CHECKLIST if c.get("enabled", True)]

        # ③④ 加载 Baseline + 企业 Override/Custom 规则，计算启用规则集
        enabled_rules = get_enabled_rules([c["id"] for c in checklist])

        batch = BatchAuditResult(
            task_id=task_id,
            folder_path=str(folder.resolve()),
            folder_name=folder_name or folder.name,
            status=AuditStatus.PENDING,
            created_at=now,
            total_files=len(pdf_files),
            files=[
                FileAuditResult(file_path=f, file_name=Path(f).name)
                for f in pdf_files
            ],
        )

        self._active_tasks[task_id] = batch
        self._task_locks[task_id] = asyncio.Lock()
        self._save_task_to_db(batch)

        # 保存 checklist 与启用规则到任务（用于审核时使用）
        batch._checklist = checklist  # type: ignore
        batch._enabled_rules = enabled_rules  # type: ignore

        return batch

    async def run_task(self, task_id: str,
                        progress_callback: Optional[ProgressCallback] = None):
        """执行审核任务（幂等：非 PENDING 状态不重复执行）"""
        if task_id not in self._active_tasks:
            raise ValueError(f"任务不存在: {task_id}")

        batch = self._active_tasks[task_id]
        # 任务级锁：防止重复启动并发执行同一任务
        lock = self._task_locks.setdefault(task_id, asyncio.Lock())
        async with lock:
            # 幂等守卫：仅 PENDING 允许启动，避免重复点击重复调 AI / 重复写报告
            if batch.status != AuditStatus.PENDING:
                return

            checklist = getattr(batch, "_checklist", DEFAULT_CHECKLIST)
            enabled_rules = getattr(batch, "_enabled_rules", EFFECTIVE_RULES)

            batch.status = AuditStatus.AUDITING
            batch.model_version = AI_CONFIG.get("model", "") or ""
            batch.rules_version = getattr(batch, "audit_standard", "Baseline V1.0") or "Baseline V1.0"
            semaphore = asyncio.Semaphore(AUDIT_CONFIG["max_concurrent_files"])

            async def audit_one(file_result: FileAuditResult):
                async with semaphore:
                    await self._audit_single_file(file_result, checklist, enabled_rules,
                                                  progress_callback, task_id)

            # 并发审核所有文件
            tasks = [audit_one(f) for f in batch.files]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # 检查被吞掉的异常：将异常文件标记为 FAILED 并记录（不再静默）
            for file_result, res in zip(batch.files, results):
                if isinstance(res, Exception):
                    file_result.status = AuditStatus.FAILED
                    file_result.error = str(res)[:500]
                    print(f"[task {task_id}] 文件审核异常: {file_result.file_name} -> {res}")

            # 汇总
            self._finalize_batch(batch)

            # 生成汇总报告
            try:
                batch = ReportWriter.write_batch_summary(batch)
            except Exception as e:
                print(f"生成汇总报告失败: {e}")

            # 批次状态：全部失败 → FAILED；部分失败 → PARTIAL；否则 COMPLETED
            batch.completed_at = datetime.now().isoformat()
            if batch.total_files > 0 and batch.failed_files == batch.total_files:
                batch.status = AuditStatus.FAILED
            elif batch.failed_files > 0:
                batch.status = AuditStatus.PARTIAL
            else:
                batch.status = AuditStatus.COMPLETED
            self._save_task_to_db(batch)

            if progress_callback:
                await progress_callback("batch_completed", "批量审核完成",
                                        batch.model_dump(exclude={"files": {"__all__": {
                                            "thumbnail", "extracted_text", "title_block_text"}}}))

    async def _audit_single_file(self, result: FileAuditResult,
                                   checklist: List[Dict],
                                   enabled_rules: List[Dict],
                                   progress_callback: Optional[ProgressCallback],
                                   task_id: str):
        """审核单个文件（10 步流水线落地）"""
        start_time = time.time()
        result.started_at = datetime.now().isoformat()
        result.enabled_rules = [{
            "id": r["id"], "name": r["name"], "name_zh": r.get("name_zh", ""),
            "category": r.get("category", ""), "severity": r.get("severity", ""),
            "execution": r.get("execution", ""), "finding_type": r.get("finding_type", ""),
            "standard_source": r.get("standard_source", "BASELINE"),
        } for r in enabled_rules]
        # 持久化元信息（写入每张文件，供重启后恢复展示）
        result.model_version = AI_CONFIG.get("model", "") or ""
        result.rules_version = getattr(result, "audit_standard", "Baseline V1.0") or "Baseline V1.0"

        try:
            # ① 读取图纸
            if progress_callback:
                await progress_callback("file_started", f"开始审核: {result.file_name}",
                                        {"file_name": result.file_name, "task_id": task_id})

            result.status = AuditStatus.PRECHECKING
            # 单次打开 PDF：文本提取 + 标题栏区域文本 + 缩略图 + 规则检查 + 渲染分块
            with PDFProcessor(result.file_path) as proc:
                result.page_count = proc.page_count

                # ② 提取结构化工程信息（矢量文本 + 标题栏区域文本 + 缩略图）
                result.extracted_text = proc.extract_text()
                result.title_block_text = proc.extract_title_block_text()

                try:
                    result.thumbnail = proc.render_thumbnail(0, max_width=300)
                except Exception:
                    pass

                # ②③④⑤ 规则前置检查 + 确定性规则执行
                if progress_callback:
                    await progress_callback("prechecking", f"规则前置检查: {result.file_name}",
                                            {"file_name": result.file_name})

                checker = RuleChecker()
                result.precheck_issues, result.title_block_info = checker.run(
                    result.extracted_text, result.title_block_text or None)
                # 自定义正则规则（并入前置检查）
                result.precheck_issues += run_custom_regex_checks(result.extracted_text)

                # ⑤ Deterministic 先算（DFM-001/002、GDT-001 等计算规则）
                engine = RuleEngine(enabled_rules)
                result.deterministic_issues = engine.run(result.extracted_text)

                result.precheck_passed = not any(
                    i.severity == Severity.BLOCK
                    for i in result.precheck_issues + result.deterministic_issues
                )

                # ③④ PDF 渲染分块（与读取共用同一次打开）
                if progress_callback:
                    await progress_callback("rendering", f"渲染图纸切片: {result.file_name}",
                                            {"file_name": result.file_name})

                result.status = AuditStatus.RENDERING
                chunks = proc.generate_chunks()

            # ⑥⑦ Hybrid 分块审核 + AI 综合审核
            if progress_callback:
                await progress_callback("ai_auditing", f"AI 审核中: {result.file_name}",
                                        {"file_name": result.file_name, "chunks": len(chunks)})

            result.status = AuditStatus.AUDITING

            async def file_progress(stage: str, msg: str):
                if progress_callback:
                    await progress_callback(stage, f"[{result.file_name}] {msg}",
                                            {"file_name": result.file_name})

            check_results, overall_comment = await self.ai_auditor.audit_file(
                result.file_name, chunks, enabled_rules,
                result.title_block_info, result.precheck_issues + result.deterministic_issues,
                file_progress
            )

            result.check_results = check_results
            result.overall_comment = overall_comment
            result.ai_issues = [
                issue for cr in check_results for issue in cr.issues
            ]

            # ⑧⑨ 证据验证 + 去重/冲突处理
            result.ai_issues = self._dedup_findings(result.ai_issues)

            # 汇总统计
            all_issues = (result.precheck_issues + result.deterministic_issues
                          + result.ai_issues)
            result.total_issues = len(all_issues)
            result.block_count = sum(1 for i in all_issues if i.severity == Severity.BLOCK)
            result.warning_count = sum(1 for i in all_issues if i.severity == Severity.WARNING)
            result.info_count = sum(1 for i in all_issues if i.severity == Severity.INFO)
            result.passed = result.block_count == 0

            # ⑩ 生成报告
            if progress_callback:
                await progress_callback("reporting", f"生成报告: {result.file_name}",
                                        {"file_name": result.file_name})

            result.status = AuditStatus.REPORTING
            result.duration_seconds = time.time() - start_time  # 报告生成前计算耗时
            result = ReportWriter.write_file_report(result)

            result.status = AuditStatus.COMPLETED

        except PDFOpenError as e:
            result.status = AuditStatus.FAILED
            result.error = str(e)
            result.overall_comment = f"PDF 读取失败: {e}"
            # 给出明确的预检问题，便于报告与界面展示失败原因
            result.precheck_issues.append(IssueItem(
                id="rule_PDF_OPEN",
                rule_id="PDF-OPEN",
                rule_name="PDF 读取失败",
                finding_type="DOCUMENT_CONTROL",
                category="DOC",
                category_name="图纸完整性",
                severity=Severity.WARNING,
                title="PDF 无法读取",
                description=str(e),
                suggestion="请检查文件是否为有效的未加密 PDF。",
                location="文件",
                source="rule",
            ))
            if progress_callback:
                await progress_callback("file_failed", f"PDF 读取失败: {result.file_name} - {e}",
                                        {"file_name": result.file_name, "error": str(e)})

        except Exception as e:
            result.status = AuditStatus.FAILED
            result.error = str(e)[:500]
            result.overall_comment = f"审核失败: {str(e)}"
            if progress_callback:
                await progress_callback("file_failed", f"审核失败: {result.file_name} - {e}",
                                        {"file_name": result.file_name, "error": str(e)})

        finally:
            result.duration_seconds = time.time() - start_time
            result.completed_at = datetime.now().isoformat()
            # 每张图纸完成后立即落库（重启后可按任务恢复进度与完整详情）
            try:
                self._save_file_to_db(task_id, result)
            except Exception as _e:
                print(f"保存文件进度失败 {result.file_name}: {_e}")

            if progress_callback:
                await progress_callback("file_completed", f"完成: {result.file_name}",
                                        result.model_dump(exclude={
                                            "thumbnail", "extracted_text", "title_block_text"}))

    @staticmethod
    def _dedup_findings(issues: List[IssueItem]) -> List[IssueItem]:
        """
        ⑨ 去重/冲突处理：
        - 同一 rule_id + 同一定位 + 同一 finding_type 只保留一条
        - 冲突时保留严重度更高、置信度更高的一条
        - 同一规则的确定性结果优先于 AI 结果（确定性由实际数值计算得出）
        """
        sev_rank = {Severity.BLOCK: 3, Severity.WARNING: 2, Severity.INFO: 1}
        seen: Dict[tuple, IssueItem] = {}

        def _prefer(cur, new):
            """返回应保留的条目"""
            # 同一规则：确定性结果优先于 AI
            if new.rule_id == cur.rule_id:
                if cur.source == "deterministic" and new.source == "ai":
                    cur.evidence = list(dict.fromkeys(cur.evidence + new.evidence))
                    if not cur.calculation and new.calculation:
                        cur.calculation = new.calculation
                    return cur
                if new.source == "deterministic" and cur.source == "ai":
                    new.evidence = list(dict.fromkeys(new.evidence + cur.evidence))
                    if not new.calculation and cur.calculation:
                        new.calculation = cur.calculation
                    return new
            cur_rank = sev_rank.get(cur.severity, 0)
            new_rank = sev_rank.get(new.severity, 0)
            if new_rank > cur_rank:
                return new
            if new_rank == cur_rank and new.confidence > cur.confidence:
                cur.evidence = list(dict.fromkeys(cur.evidence + new.evidence))
                return cur
            return cur

        for iss in issues:
            key = (iss.rule_id or iss.id, iss.location, iss.finding_type)
            if key not in seen:
                seen[key] = iss
            else:
                seen[key] = _prefer(seen[key], iss)
        return list(seen.values())

    def _finalize_batch(self, batch: BatchAuditResult):
        """汇总批量结果"""
        completed = [f for f in batch.files if f.status == AuditStatus.COMPLETED]
        failed = [f for f in batch.files if f.status == AuditStatus.FAILED]

        batch.completed_files = len(completed)
        batch.failed_files = len(failed)

        all_issues = []
        for f in batch.files:
            all_issues.extend(f.precheck_issues + f.deterministic_issues + f.ai_issues)

        batch.total_issues = len(all_issues)
        batch.block_count = sum(1 for i in all_issues if i.severity == Severity.BLOCK)
        batch.warning_count = sum(1 for i in all_issues if i.severity == Severity.WARNING)
        batch.info_count = sum(1 for i in all_issues if i.severity == Severity.INFO)

        passed_count = sum(1 for f in completed if f.passed)
        batch.pass_rate = (passed_count / len(completed) * 100) if completed else 0.0

    def get_task(self, task_id: str) -> Optional[BatchAuditResult]:
        """获取任务结果"""
        return self._active_tasks.get(task_id)

    def get_active_tasks(self) -> List[BatchAuditResult]:
        """获取所有活跃任务"""
        return list(self._active_tasks.values())
