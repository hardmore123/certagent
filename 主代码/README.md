# 主代码（报告草稿准确性核对 核心代码库）

来源：工作区 `报告草稿准确性核对/`，项目二的核心代码库。

## 角色
项目二的全部核心代码：核对引擎 + LLM 可选子包 + Web + 前端 + 测试 + 内置样本 + spec。

## 入口文档
- `交接文档.md`：**项目二最详尽交接说明**（314 行，推荐先读）
- `README.md`：快速上手、范围、样本结构基线
- `design.md`：设计摘要（架构/数据模型/正确性属性）
- `tasks.md`：P0–P7 任务分解与状态
- `LLM_RELEASE_GATE.md`：LLM 发布门禁清单与回滚
- `交付清单.md`：交付物清单

## 目录
- `cli.py`：命令行入口
- `report_verify/`：核对核心包（确定性主链 + llm/ 可选子包）
- `webapi/`：FastAPI（上传/进度/行级差异/确认/下载/LLM证据 + 任务计时 + 重启恢复）
- `frontend/index.html`：单文件前端（三视图 + AI只读区 + 实时计时）
- `rules/normalization.json`：归一化规则（版本 normalized-v2）
- `samples/`：内置样本（data + expected_outputs + manifest + gold_baseline）
- `docs/`：背景文档 + specs/（两套完整 spec 副本：report-draft-verify + report-draft-llm-integration）
- `scripts/`：一键脚本（run_web/run_sample/run_tests/check_llm）
- `tests/`：标准库 unittest（357 项，核对核心 + LLM 子包 + Web）

## 排除说明
复制自原仓库，已排除 `.git/ __pycache__/ runs/`（3GB 产物）；`.env`（真实密钥）已排除，用 `.env.example` 代替。

## 快速启动
见 `../README_交接总览.md` 第 4 节，或 `交接文档.md` 第 2 节。
