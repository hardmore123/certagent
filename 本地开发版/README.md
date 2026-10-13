# 本地开发版（list-merge-demo 开发主目录 + CertAgent/demo 变体）

来源：工作区 `list-merge-demo/`（日常开发主目录）+ `_变体_CertAgent-demo/`（= CertAgent/demo 导出副本）。

## 角色
日常开发调试。改代码在这里改。

## 内容
- 顶层各文件：`cli.py` `README.md` `requirements.txt` `check_stats.py` `test_llm.py` `test_diff_diag.py` `记忆库说明.md` `问题排查日志.md`
- `项目说明_交接.md`：**本项目最详尽的交接说明**（推荐先读）
- `compare_core/` `graph/` `webapi/` `frontend/` `tests/` `fixtures/`：核心代码与测试
- `samples/`：项目自带的完整输入输出样例（inputs + expected_outputs）
- `_变体_CertAgent-demo/`：从 CertAgent/demo 导出的变体副本，与主目录核心一致

## 与服务器版差异
核心代码完全一致，差异仅在环境特性。见 `../README_交接总览.md` 第 3 节。

## 数据结构与实现思路
集中讲透的文档见 `../数据结构与实现思路详解.md`（含数据模型 Row/DiffItem/GroupDiff/Suggestion/AuditReport 字段表、记忆库记录结构、规则YAML结构、运行产物结构、数据流转关系图）。本目录的 `compare_core/models.py` 是数据模型的源代码定义，`记忆库说明.md` 是记忆库的详细说明。

## 排除说明
复制自原仓库，已排除 `.git/` `node_modules/` `__pycache__/` `runs/`；`.env`（密钥）已排除，用 `.env.example` 代替。
