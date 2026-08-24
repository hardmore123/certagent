"""任务执行器：asyncio.Task + Semaphore 并发控制。"""
from __future__ import annotations

import asyncio
import traceback
from pathlib import Path

from .jobs import JobRecord, registry
from .settings import settings


class JobRunner:
    def __init__(self):
        self._sem = asyncio.Semaphore(settings.MAX_CONCURRENT_JOBS)

    def submit(self, rec: JobRecord) -> None:
        asyncio.create_task(self._execute(rec))

    async def _execute(self, rec: JobRecord) -> None:
        async with self._sem:
            try:
                rec.status = "running"
                rec.stage = "解析"
                rec.progress = 0.1
                rec.save()

                # 在线程池里跑同步 pipeline
                import sys
                sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

                from compare_core import nodes, trace
                from compare_core.parser import load_rows_json, parse_document

                loop = asyncio.get_event_loop()

                # 解析阶段
                def _parse():
                    trace.new_run()
                    # 检测上传文件的实际扩展名
                    orig_doc = rec.job_dir / "orig.doc"
                    plm_doc = rec.job_dir / "plm.doc"
                    state = {}

                    # Word COM 必须在 CoInitialize 过的线程里调用
                    import pythoncom

                    def _load_one(path: Path):
                        """按文件类型分派解析，返回 (rows, docx_path)：
                        - JSON fixture（内容以 [ 开头）→ load_rows_json，docx_path=None
                        - 真正的 .docx → python-docx（无 COM），docx_path=原路径
                        - 老 .doc → 自动转 .docx（LibreOffice/Word 子进程）再解析，docx_path=转换后路径

                        docx_path 供 apply 阶段作格式模板（字体/字号/页面/列宽）。
                        """
                        from compare_core.parser import load_rows_json, parse_docx
                        from compare_core.parser.converter import ensure_docx

                        # 1) JSON fixture
                        try:
                            content = path.read_text(encoding="utf-8")
                            if content.strip().startswith("["):
                                return load_rows_json(str(path)), None
                        except Exception:
                            pass

                        # 2) 尝试直接当 .docx 解析
                        try:
                            return parse_docx(str(path)), str(path)
                        except Exception:
                            pass  # 不是有效 docx

                        # 3) 老 .doc → 自动转换（子进程，不污染主线程）
                        docx_path = ensure_docx(str(path), work_dir=str(path.parent / "_converted"))
                        return parse_docx(docx_path), docx_path

                    state["rows_orig"], _ = _load_one(orig_doc)
                    state["rows_plm"], plm_docx = _load_one(plm_doc)
                    # PLM(新版本=输出骨架) 作格式模板
                    if plm_docx:
                        state["template_docx"] = plm_docx
                    return state

                state = await loop.run_in_executor(None, _parse)

                rec.stage = "比对"
                rec.progress = 0.4
                rec.save()

                # judge + suggest
                def _judge_suggest():
                    # LLM fuzzy 候选提名：任务级勾选 或 全局设置任一开启即启用
                    state["fuzzy_llm"] = bool(rec.fuzzy_llm) or settings.ENABLE_FUZZY_LLM
                    state["fuzzy_threshold"] = settings.FUZZY_THRESHOLD
                    state.update(nodes.judge_node(state))
                    state["mode"] = "mock"
                    state["suggest_source"] = "groups"
                    state.update(nodes.suggest_node(state))
                    return state

                state = await loop.run_in_executor(None, _judge_suggest)

                rec.diff_count = len(state.get("diffs", []))
                rec.status = "review"
                rec.stage = "等待确认"
                rec.progress = 0.7
                rec.state = state  # 保留在内存中，等用户决策
                rec.save()

            except Exception as e:
                rec.status = "failed"
                rec.error = f"{type(e).__name__}: {e}\n{traceback.format_exc()[-500:]}"
                rec.save()

    async def apply_decisions(
        self, rec: JobRecord, decisions: dict[str, object],
        reasons: dict[str, str] | None = None,
    ) -> None:
        """用户提交决策后，生成输出文件。

        decisions 值兼容 str 或 {verdict,target_key,reason}（手动匹配）。
        reasons 随决策落盘进长期记忆。
        """
        try:
            rec.status = "running"
            rec.stage = "生成文档"
            rec.progress = 0.85
            rec.save()

            state = rec.state
            state["decisions"] = decisions
            state["reasons"] = reasons or {}
            state["out_dir"] = str(rec.job_dir)

            from compare_core import nodes

            loop = asyncio.get_event_loop()

            def _apply():
                state.update(nodes.apply_node(state))
                # 数据守恒审计 + 补录（与 LangGraph 图一致）
                state.update(nodes.audit_node(state))
                if state.get("audit_report") and state["audit_report"].status == "critical":
                    state.update(nodes.repair_node(state))
                state.update(nodes.memory_node(state))
                return state

            state = await loop.run_in_executor(None, _apply)

            rec.out_merged = state.get("out_merged", "")
            rec.out_compare = state.get("out_compare", "")
            _audit = state.get("audit_report")
            if _audit is not None:
                rec.state["audit"] = _audit.model_dump()
            rec.status = "done"
            rec.stage = "完成"
            rec.progress = 1.0
            rec.save()

        except Exception as e:
            rec.status = "failed"
            rec.error = f"{type(e).__name__}: {e}"
            rec.save()


runner = JobRunner()
