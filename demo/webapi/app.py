"""FastAPI 应用：路由 + 中间件 + 前端托管。"""
from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .auth import create_token, get_current_user, verify_password
from .analytics import AnalyticsMiddleware, get_summary
from .jobs import registry
from .runner import runner
from .schemas import DecisionRequest, DiffItemResponse, LoginRequest, LoginResponse
from .settings import settings

app = FastAPI(title="认证清单整合 API", version="1.0.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ALLOW_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 使用统计中间件（自动记录每次 API 调用）
app.add_middleware(AnalyticsMiddleware)


# 启动时恢复历史任务
@app.on_event("startup")
async def _startup():
    registry.recover()


# === 健康探针 ===
@app.get("/health")
async def health():
    return {"status": "ok"}


# === 使用统计（仅登录用户可查看）===
@app.get("/api/v1/analytics")
async def analytics(user: dict = Depends(get_current_user)):
    return get_summary()


# === 认证 ===
@app.post("/api/v1/auth/login", response_model=LoginResponse)
async def login(req: LoginRequest):
    if not verify_password(req.username, req.password):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = create_token(req.username)
    return LoginResponse(token=token, user={"username": req.username, "role": "admin"})


# === 任务管理 ===
@app.post("/api/v1/jobs", status_code=201)
async def create_job(
    file_orig: UploadFile = File(..., description="输入 A（原始清单·人工整理 / 旧版本·变更前）"),
    file_plm: UploadFile = File(..., description="输入 B（PLM 导出·新品 / 新版本·变更后）"),
    fuzzy_llm: bool = Form(False, description="是否启用 LLM 智能配对（对规则漏配的残余行提名疑似同一件）"),
    user: dict = Depends(get_current_user),
):
    rec = registry.create(owner=user["username"])
    rec.file_orig = file_orig.filename or "orig"
    rec.file_plm = file_plm.filename or "plm"
    rec.fuzzy_llm = fuzzy_llm
    rec.save()

    # 保存上传文件
    orig_path = rec.job_dir / "orig.doc"
    plm_path = rec.job_dir / "plm.doc"
    with open(orig_path, "wb") as f:
        shutil.copyfileobj(file_orig.file, f)
    with open(plm_path, "wb") as f:
        shutil.copyfileobj(file_plm.file, f)

    # 异步执行
    runner.submit(rec)
    return {"job_id": rec.job_id, "status": "queued"}


@app.get("/api/v1/jobs")
async def list_jobs(user: dict = Depends(get_current_user)):
    jobs = registry.list_all(owner=user["username"])
    return [j.to_summary() for j in jobs]


@app.get("/api/v1/jobs/{job_id}")
async def get_job(job_id: str, user: dict = Depends(get_current_user)):
    rec = registry.get(job_id)
    if not rec:
        raise HTTPException(404, "任务不存在")
    return rec.to_summary()


@app.get("/api/v1/jobs/{job_id}/diffs")
async def get_diffs(job_id: str, user: dict = Depends(get_current_user)):
    """获取 diff 列表供确认页使用。"""
    rec = registry.get(job_id)
    if not rec or not rec.state.get("diffs"):
        raise HTTPException(404, "任务不存在或尚未完成比对")

    from compare_core.differ import order_for_output
    from compare_core.models import DiffType
    from compare_core.suggester.base import rule_suggest

    raw_diffs = rec.state["diffs"]
    suggestions = rule_suggest(raw_diffs)
    sugg_by_key = {s.diff_key: s for s in suggestions}
    # 按"最终文档行顺序"返回（表一在前、表二在后，旧版本独有行按关键件组插入）。
    # 与 writer 共用 differ.ordering，保证确认页顺序 == 输出文档顺序。
    diffs = order_for_output(raw_diffs)

    # 与 writer._SOURCE_LABEL 保持一致（三.23 定稿 A/B 语义：PLM=新版本骨架）
    source_label = {
        DiffType.ONLY_PLM: "新增(PLM新版本)",
        DiffType.ONLY_ORIG: "旧版本保留",
        DiffType.CHANGED: "两侧(差异)",
        DiffType.SAME: "两侧",
    }

    # 展示字段必须覆盖 diff_engine._VERIFY_FIELDS 的全部内容列，
    # 否则会出现"后端判为内容不同、前端却无字段可高亮"（备注/本次使用 是表2特有列）。
    _FIELDS = ["位号", "关键件名称", "型号", "规格材料", "制造商",
               "生产企业", "认证标准", "证书号", "本次使用", "备注"]

    def _side(r):
        """一侧完整行数据（含源文件行号），供并排对照视图使用；无该侧则 None。"""
        if r is None:
            return None
        data = {f: (getattr(r, f, "") or "") for f in _FIELDS}
        data["_row_index"] = r.row_index      # 源文件表内行号
        data["_table"] = r.table
        data["_group"] = r.group or ""
        return data

    items = []
    for idx, d in enumerate(diffs, start=1):
        # 与 writer 展示一致：ONLY_ORIG(旧版本独有) 取 orig 侧，其余取 PLM 侧（新版本骨架）
        row = (d.orig or d.plm) if d.type == DiffType.ONLY_ORIG else (d.plm or d.orig)
        s = sugg_by_key.get(d.key)
        # 并排对照视图：所有类型都返回两侧完整行（缺失侧为 None）
        a_row = _side(d.orig)
        b_row = _side(d.plm)
        # 兼容旧字段：CHANGED 行的 A/B 对比数据（合并视图在用）
        orig_data = None
        plm_data = None
        if d.type == DiffType.CHANGED and d.orig and d.plm:
            orig_data = {f: (getattr(d.orig, f, "") or "") for f in _FIELDS}
            plm_data = {f: (getattr(d.plm, f, "") or "") for f in _FIELDS}
        items.append({
            "key": d.key,
            "type": d.type.value,
            "table": d.table,
            "confidence": d.confidence.value,
            # 最终文档中的行号（1-based，全局连续：表一在前表二在后）+ 分组标题，供确认页对照与分段
            "output_index": idx,
            "group": (row.group if row else "") or "",
            "关键件名称": row.关键件名称 if row else "",
            "型号": row.型号 if row else "",
            "规格材料": row.规格材料 if row else "",
            "制造商": row.制造商 if row else "",
            "生产企业": row.生产企业 if row else "",
            "认证标准": row.认证标准 if row else "",
            "证书号": row.证书号 if row else "",
            "changed_fields": d.changed_fields,
            "source_label": source_label.get(d.type, ""),
            "action": s.action if s else "",
            "reason": s.reason if s else "",
            # 记忆反哺留痕：前端可据此给"历史被否/被确认"打标
            "memory_applied": bool(s.memory_applied) if s else False,
            "memory": (s.memory_hint.model_dump() if (s and s.memory_hint) else None),
            "orig_data": orig_data,
            "plm_data": plm_data,
            # 并排对照视图用：两侧完整行（含源行号），缺失侧为 null
            "a_row": a_row,
            "b_row": b_row,
            # LLM fuzzy 提名配对信息（pair_reason 非空即"AI 疑似同一件，待确认"）
            "pair_reason": d.pair_reason,
            "pair_confidence": d.pair_confidence,
        })
    return items


@app.post("/api/v1/jobs/{job_id}/decisions")
async def submit_decisions(
    job_id: str,
    req: DecisionRequest,
    user: dict = Depends(get_current_user),
):
    rec = registry.get(job_id)
    if not rec:
        raise HTTPException(404, "任务不存在")
    if rec.status != "review":
        raise HTTPException(400, f"任务状态不允许提交决策: {rec.status}")

    # 归一化决策载荷：DecisionDetail → 纯 dict，字符串原样，交给引擎（引擎不依赖 web 模型）。
    decisions = {
        k: (v.model_dump(exclude_none=True) if hasattr(v, "model_dump") else v)
        for k, v in req.decisions.items()
    }
    await runner.apply_decisions(rec, decisions, req.reasons)
    return {"status": rec.status, "out_merged": rec.out_merged, "out_compare": rec.out_compare}


@app.get("/api/v1/jobs/{job_id}/result/merged")
async def download_merged(job_id: str, user: dict = Depends(get_current_user)):
    rec = registry.get(job_id)
    if not rec or not rec.out_merged:
        raise HTTPException(404, "文件不存在")
    return FileResponse(rec.out_merged, filename="整合版关键件清单.docx")


@app.get("/api/v1/jobs/{job_id}/result/compare")
async def download_compare(job_id: str, user: dict = Depends(get_current_user)):
    rec = registry.get(job_id)
    if not rec or not rec.out_compare:
        raise HTTPException(404, "文件不存在")
    return FileResponse(rec.out_compare, filename="变更前后对照表.docx")


@app.get("/api/v1/jobs/{job_id}/result")
async def get_result(job_id: str, user: dict = Depends(get_current_user)):
    rec = registry.get(job_id)
    if not rec:
        raise HTTPException(404, "任务不存在")
    changes = []
    if rec.state.get("changes"):
        changes = [c.model_dump() for c in rec.state["changes"]]
    from collections import Counter
    diff_summary = {}
    if rec.state.get("diffs"):
        diff_summary = dict(Counter(d.type.value for d in rec.state["diffs"]))
    return {
        "job_id": rec.job_id,
        "merged_path": rec.out_merged,
        "compare_path": rec.out_compare,
        "changes": changes,
        "diff_summary": diff_summary,
        "audit": rec.state.get("audit"),
    }


# === 前端静态托管（生产模式）===
_FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
_ASSETS_DIR = _FRONTEND_DIR / "assets"
if _FRONTEND_DIR.exists() and _ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(_ASSETS_DIR)), name="frontend-assets")

    @app.get("/{full_path:path}")
    async def _spa_fallback(full_path: str):
        """SPA fallback：所有未匹配路径 → index.html"""
        index = _FRONTEND_DIR / "index.html"
        if index.exists():
            return FileResponse(str(index))
        raise HTTPException(404)
