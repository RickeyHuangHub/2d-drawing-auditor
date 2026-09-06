"""
2D图纸审核高手 - FastAPI 主入口
启动：python main.py
访问：http://localhost:8000
"""
import asyncio
import json
import os
import sys
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, UploadFile, File, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# 确保项目根目录在 path 中
BASE_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(BASE_DIR))

from config import (FRONTEND_DIR, AI_CONFIG, DEFAULT_CHECKLIST,
                    EFFECTIVE_RULES, RULE_CATEGORIES, FINDING_TYPES,
                    FINDING_TYPE_LABEL_ZH, BASELINE_INSTRUCTION,
                    CUSTOM_OVERRIDES, CUSTOM_BASELINE_RULES, DATA_DIR,
                    UPLOAD_CONFIG, AUTH_CONFIG,
                    save_ai_config, get_masked_api_key)
from backend.models import TaskCreateRequest, AuditStatus
from backend.task_manager import TaskManager

app = FastAPI(title="Drawing Audit Expert (2D图纸审核高手)", version="1.1.0")

# 全局任务管理器
task_manager = TaskManager()

# WebSocket 连接管理
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: Dict[str, Any]):
        disconnected = []
        for conn in self.active_connections:
            try:
                await conn.send_json(message)
            except Exception:
                disconnected.append(conn)
        for conn in disconnected:
            self.disconnect(conn)

manager = ConnectionManager()


# ── 审计日志（③：关键操作留痕，供生产/合规追溯）──────────────

def _write_audit_log(action: str, detail: str = ""):
    """追加写入审计日志 data/audit.log（失败不影响主流程）"""
    try:
        log_path = AUTH_CONFIG.get("audit_log_path") or (DATA_DIR / "audit.log")
        log_path.parent.mkdir(exist_ok=True, parents=True)
        ts = datetime.now().isoformat()
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"{ts} | {action} | {detail}\n")
    except Exception:
        pass


# ── 可选鉴权（③）：设置环境变量 AUTH_TOKEN 后启用 /api/* 鉴权 ──
# 默认关闭（token 为空），本地使用完全不受影响；生产部署时开启。
@app.middleware("http")
async def auth_audit_middleware(request: Request, call_next):
    path = request.url.path
    token = AUTH_CONFIG.get("token") or ""
    if token and path.startswith("/api/") and not path.startswith("/api/config"):
        expected = "Bearer " + token
        auth_header = request.headers.get("Authorization", "")
        # 兼容 query 传 token（供非浏览器客户端使用）
        if auth_header != expected and request.query_params.get("token") != token:
            return JSONResponse({"detail": "未授权：缺少或错误的访问令牌"}, status_code=401)

    if path.startswith("/api/") and request.method in ("POST", "PUT", "DELETE"):
        _write_audit_log(f"api_{request.method.lower()}", f"{request.method} {path}")

    response = await call_next(request)
    return response

@app.get("/")
async def index():
    """首页"""
    index_path = FRONTEND_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return JSONResponse({"error": "前端文件不存在"}, status_code=404)


# 挂载前端静态资源
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


# ── API 路由 ────────────────────────────────────────────────────

@app.get("/api/config")
async def get_config():
    """获取前端配置（API Key 脱敏返回，不暴露明文）"""
    ai_configured = bool(AI_CONFIG["api_key"])
    return {
        "ai_configured": ai_configured,
        "demo_mode": not ai_configured,
        "model": AI_CONFIG["model"],
        "base_url": AI_CONFIG["base_url"],
        "api_key_masked": get_masked_api_key(),
        "default_checklist": DEFAULT_CHECKLIST,
        "supported_extensions": [".pdf"],
        "audit_standard": "Baseline V1.0",
        "rule_count": len(EFFECTIVE_RULES),
        "baseline_rule_count": len([r for r in EFFECTIVE_RULES if not r.get("custom")]),
        "custom_rule_count": len([r for r in EFFECTIVE_RULES if r.get("custom")]),
        "override_count": len(CUSTOM_OVERRIDES),
    }


class AIConfigRequest(BaseModel):
    """用户在网页界面输入的 AI 配置"""
    base_url: str = ""
    api_key: str = ""
    model: str = ""


@app.put("/api/config")
async def update_config(req: AIConfigRequest):
    """保存用户在网页界面输入的 AI 配置到本地文件（不提交到 GitHub）"""
    if not req.api_key.strip():
        raise HTTPException(status_code=400, detail="API Key 不能为空")
    if not req.base_url.strip():
        raise HTTPException(status_code=400, detail="Base URL 不能为空")
    if not req.model.strip():
        raise HTTPException(status_code=400, detail="Model 名称不能为空")

    ok = save_ai_config(req.base_url, req.api_key, req.model)
    if not ok:
        raise HTTPException(status_code=500, detail="保存配置失败，请检查 data 目录权限")

    return {
        "success": True,
        "message": "AI 配置已保存到本地（data/ai_config.json，不提交到 GitHub）",
        "ai_configured": True,
        "model": req.model,
        "api_key_masked": get_masked_api_key(),
    }


@app.get("/api/checklist")
async def get_checklist():
    """获取审核检查项列表"""
    return {"checklist": DEFAULT_CHECKLIST}


@app.get("/api/rules")
async def get_rules():
    """
    Baseline V1.0 规则库（含企业 Override / Custom 规则）。
    用于前端规则库展示与规则管理。
    """
    return {
        "audit_standard": "Baseline V1.0",
        "instruction": BASELINE_INSTRUCTION,
        "allowed_results": ["PASS", "WARNING", "CRITICAL", "NEEDS_REVIEW", "NOT_APPLICABLE"],
        "finding_types": [
            {"id": ft, "name": FINDING_TYPE_LABEL_ZH.get(ft, ft)}
            for ft in FINDING_TYPES
        ],
        "categories": [
            {
                "id": c["id"],
                "name": c["name"],
                "icon": c.get("icon", ""),
                "desc": c.get("desc", ""),
                "rules": [
                    {
                        "id": r["id"],
                        "name": r["name"],
                        "name_zh": r.get("name_zh", ""),
                        "severity": r.get("severity", ""),
                        "execution": r.get("execution", ""),
                        "finding_type": r.get("finding_type", ""),
                        "standard_source": r.get("standard_source", "BASELINE"),
                        "parameters": r.get("parameters", {}),
                        "custom": r.get("custom", False),
                        "override": r.get("override", None),
                    }
                    for r in EFFECTIVE_RULES if r["category"] == c["id"]
                ],
            }
            for c in RULE_CATEGORIES
        ],
        "custom_rules": [r for r in EFFECTIVE_RULES if r.get("custom")],
        "overrides": CUSTOM_OVERRIDES,
    }


@app.post("/api/tasks")
async def create_task(request: TaskCreateRequest):
    """创建审核任务"""
    try:
        batch = task_manager.create_task(
            folder_path=request.folder_path,
            checklist_ids=request.checklist_ids,
            recursive=request.recursive,
        )
        return {
            "task_id": batch.task_id,
            "folder_name": batch.folder_name,
            "total_files": batch.total_files,
            "files": [
                {"file_name": f.file_name, "file_path": f.file_path}
                for f in batch.files
            ],
        }
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/upload")
async def upload_drawings(files: List[UploadFile] = File(...),
                          checklist_ids: Optional[str] = None,
                          recursive: bool = True):
    """拖拽/选择上传 PDF 图纸：保存到临时目录并创建审核任务。
    安全措施：单文件大小上限、分块写入、真实 PDF 文件头校验、单批数量上限。"""
    import uuid as _uuid
    if not files:
        raise HTTPException(status_code=400, detail="未收到文件")

    # 过滤出 PDF 文件
    pdf_files = []
    for f in files:
        name = (f.filename or "").strip()
        if name.lower().endswith(".pdf"):
            pdf_files.append((name, f))
    if not pdf_files:
        raise HTTPException(status_code=400, detail="只支持 PDF 图纸文件")

    # 限制单批数量
    MAX_FILES = UPLOAD_CONFIG["max_files"]
    if len(pdf_files) > MAX_FILES:
        raise HTTPException(status_code=400, detail=f"一次最多上传 {MAX_FILES} 张图纸")

    MAX_SIZE = UPLOAD_CONFIG["max_file_size"]
    CHUNK = UPLOAD_CONFIG["chunk_size"]

    # 保存到 data/uploads/<task_id>/
    task_id = str(_uuid.uuid4())[:8]
    upload_dir = DATA_DIR / "uploads" / task_id
    upload_dir.mkdir(parents=True, exist_ok=True)

    saved = []
    errors = []
    for name, f in pdf_files:
        # 防止路径穿越：仅取文件名
        safe_name = os.path.basename(name.replace("\\", "/"))
        target = upload_dir / safe_name

        # 分块写入 + 大小上限（避免整文件读入内存、超大文件 DoS）
        size = 0
        try:
            with open(target, "wb") as out:
                while True:
                    chunk = await f.read(CHUNK)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_SIZE:
                        raise HTTPException(
                            status_code=413,
                            detail=f"文件 {safe_name} 超过 {MAX_SIZE // (1024*1024)}MB 上限")
                    out.write(chunk)
        except HTTPException:
            target.unlink(missing_ok=True)
            raise
        except Exception as e:
            target.unlink(missing_ok=True)
            errors.append(f"{safe_name}: 写入失败（{e}）")
            continue

        # 校验真实 PDF 文件头（不只看扩展名，防止伪装文件）
        try:
            with open(target, "rb") as fp:
                head = fp.read(1024)
            if b"%PDF-" not in head:
                target.unlink(missing_ok=True)
                errors.append(f"{safe_name}: 文件头不是有效的 PDF")
                continue
        except Exception as e:
            target.unlink(missing_ok=True)
            errors.append(f"{safe_name}: 文件校验失败（{e}）")
            continue

        saved.append(str(target))

    if not saved:
        detail = "文件保存失败"
        if errors:
            detail += "：" + "；".join(errors[:5])
        raise HTTPException(status_code=400, detail=detail)

    # 创建审核任务（复用文件夹扫描逻辑）
    try:
        batch = task_manager.create_task(
            folder_path=str(upload_dir),
            checklist_ids=(checklist_ids or "").split(",") if checklist_ids else None,
            recursive=False,
            folder_name=f"上传图纸({len(saved)})",
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"创建任务失败: {e}")

    return {
        "task_id": batch.task_id,
        "folder_name": batch.folder_name,
        "total_files": batch.total_files,
        "uploaded_files": len(saved),
        "files": [
            {"file_name": f.file_name, "file_path": f.file_path}
            for f in batch.files
        ],
    }


@app.post("/api/tasks/{task_id}/start")
async def start_task(task_id: str):
    """开始执行审核任务（异步，幂等：仅待审核任务可启动）"""
    batch = task_manager.get_task(task_id)
    if not batch:
        raise HTTPException(status_code=404, detail="任务不存在")

    # 幂等守卫：仅 PENDING 可启动，重复点击不再重复创建后台任务
    if batch.status != AuditStatus.PENDING:
        raise HTTPException(
            status_code=409,
            detail=f"任务当前状态为 {batch.status.value}，仅待审核任务可启动")

    async def progress_callback(stage: str, message: str, data: Optional[Dict] = None):
        await manager.broadcast({
            "type": "progress",
            "task_id": task_id,
            "stage": stage,
            "message": message,
            "data": data or {},
        })

    # 后台执行（run_task 内部另有任务级锁 + 状态守卫兜底）
    asyncio.create_task(task_manager.run_task(task_id, progress_callback))

    return {"status": "started", "task_id": task_id}


@app.get("/api/tasks")
async def list_tasks(limit: int = 50):
    """获取历史任务列表"""
    tasks = task_manager.get_task_history(limit)
    return {"tasks": tasks}


@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str):
    """获取任务详情（重启后自动从数据库恢复完整审核详情）"""
    batch = task_manager.get_task(task_id)
    if batch:
        return batch.model_dump(exclude={"files": {"__all__": {"thumbnail", "extracted_text", "title_block_text"}}})

    # 服务重启后：从数据库恢复完整详情（含问题/证据/规则版本）
    batch = task_manager.restore_task_from_db(task_id)
    if batch:
        return batch.model_dump(exclude={"files": {"__all__": {"thumbnail", "extracted_text", "title_block_text"}}})

    # 兜底：仅返回简化文件记录
    files = task_manager.get_task_files(task_id)
    if not files:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"task_id": task_id, "files": files, "from_db": True}


@app.get("/api/tasks/{task_id}/files/{file_index}")
async def get_file_result(task_id: str, file_index: int):
    """获取单个文件的审核详情（含缩略图；重启后从数据库恢复）"""
    batch = task_manager.get_task(task_id)
    if not batch:
        batch = task_manager.restore_task_from_db(task_id)
    if not batch or file_index < 0 or file_index >= len(batch.files):
        raise HTTPException(status_code=404, detail="文件结果不存在")

    file_result = batch.files[file_index]
    return file_result.model_dump(exclude={"extracted_text", "title_block_text"})


@app.get("/api/tasks/{task_id}/summary")
async def get_task_summary(task_id: str):
    """获取任务汇总"""
    batch = task_manager.get_task(task_id)
    if not batch:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {
        "task_id": batch.task_id,
        "folder_name": batch.folder_name,
        "status": batch.status.value,
        "total_files": batch.total_files,
        "completed_files": batch.completed_files,
        "failed_files": batch.failed_files,
        "total_issues": batch.total_issues,
        "block_count": batch.block_count,
        "warning_count": batch.warning_count,
        "info_count": batch.info_count,
        "pass_rate": batch.pass_rate,
        "summary_report_path": batch.summary_report_path,
    }


# ── WebSocket ───────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket 实时进度推送"""
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            # 客户端可以发送心跳
            try:
                msg = json.loads(data)
                if msg.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        manager.disconnect(websocket)


# ── 启动 ────────────────────────────────────────────────────────

def _find_available_port(host: str, start_port: int, max_attempts: int = 20) -> int:
    """查找可用端口，从 start_port 开始尝试，被占用则 +1 重试"""
    import socket
    for i in range(max_attempts):
        port = start_port + i
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                s.bind((host, port))
            return port
        except OSError:
            continue
    raise RuntimeError(f"从 {start_port} 到 {start_port + max_attempts - 1} 的端口都被占用")


def main():
    import uvicorn

    host = os.getenv("HOST", "127.0.0.1")
    default_port = int(os.getenv("PORT", "8080"))

    # 查找可用端口
    try:
        port = _find_available_port(host, default_port)
        if port != default_port:
            print(f"⚠️  端口 {default_port} 被占用，自动切换到端口 {port}")
    except RuntimeError as e:
        print(f"❌ 启动失败: {e}")
        print("   请关闭占用端口的程序，或设置环境变量 PORT 指定其他端口")
        input("\n按回车键退出...")
        return

    # 检查 AI 配置
    if not AI_CONFIG["api_key"]:
        print("=" * 60)
        print("⚠️  未配置 AI_API_KEY，当前为【演示模式】")
        print("   规则检查、PDF处理、报告生成正常运行")
        print("   AI审核部分返回模拟数据，可完整测试流程和界面")
        print()
        print("   配置真实 API Key 后重启即可切换为正式模式：")
        print("   set AI_API_KEY=your_api_key")
        print("   set AI_BASE_URL=https://ark.cn-beijing.volces.com/api/v3")
        print("   set AI_MODEL=doubao-vision-pro-32k")
        print("=" * 60)

    print(f"\n🚀 2D图纸审核高手 启动中...")
    print(f"   访问地址: http://{host}:{port}")
    print(f"   前端目录: {FRONTEND_DIR}")
    print(f"   数据库:   {BASE_DIR / 'data' / 'audit_history.db'}\n")
    print("   按 Ctrl+C 停止服务\n")

    # 自动打开浏览器
    try:
        webbrowser.open(f"http://{host}:{port}")
    except Exception:
        pass

    try:
        uvicorn.run(app, host=host, port=port, log_level="info")
    except Exception as e:
        print(f"\n❌ 服务运行出错: {e}")
        input("\n按回车键退出...")


if __name__ == "__main__":
    main()
