# 服务器版（CertAgent/Linux 生产部署版）

来源：工作区 `CertAgent/Linux/`（GitLab 正式仓库 `Full-Stack-Frontend/Hisense/Agents/AI_Applications/CertAgent.git` 的服务器部署分支）。

## 角色
Linux 生产部署版：nginx 子路径反代 + systemd 守护 + 解密服务对接。

## 独有内容
- `compare_core/decrypt.py` + 顶层 `test_decrypt.py`：对接解密服务，处理透明加密 docx
- `deploy/`：部署资产
  - `deploy.sh` 一键部署脚本
  - `nginx.conf` nginx 子路径配置
  - `certagent.service` systemd 单元
  - `部署与使用指南.md` / `部署问题排查日志.md` / `README.md`
- `BLUEPRINT.md`：项目原则
- `DOCS.md`：文档路由 + 目录结构
- `.env.example`：完整配置项（含解密服务、LLM、记忆库等）

## 与本地版差异
核心引擎/编排/Web/前端代码与 `本地开发版/` 完全一致，差异仅在环境特性（解密、部署资产）。不存在缺功能。

## 快速启动
见 `../README_交接总览.md` 第 3 节。部署细节见 `deploy/` 下文档。
