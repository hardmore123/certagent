# 项目一 · 认证清单整合（CertAgent / list-merge）· 交接包

> 本交接包汇集项目一（认证清单整合）的全部资产，**服务器版与本地开发版单独存放**，配详细说明，所有信息集中在本文件夹用于交接。
> 项目一与项目二（报告草稿准确性核对）的边界见 `需求与设计文档/两个项目导读.md`；本项目自带详尽交接说明见 `本地开发版/项目说明_交接.md`。
> 打包时间：2026-09-03

---

## 1. 这个项目做什么

两份 Word 关键件**清单**（A=原始/旧版本、B=PLM 新品/新版本）→ 判断差异 → AI 建议 → 人工确认（接受 / 拒绝 / 手动匹配纠正 / 其实相同 / 拆两独有）→ 生成【整合版关键件清单】+【变更前后对照表】，并把决策沉淀进长期记忆用于持续优化。

关键动词是**合并 / 整合**（不是"核对"——核对是项目二做的事）。

状态：**已完成、已部署上线、已上传 GitLab**。

---

## 2. 交接包目录结构

```
认证清单整合_交接包/
├── README_交接总览.md            ← 本文件（总入口）
├── 数据结构与实现思路详解.md      ← 集中讲透整体实现思路 + 全部数据结构设计（推荐先读）
│
├── 服务器版/                      ← 来自 CertAgent/Linux（生产部署版）
├── 本地开发版/                    ← 来自 list-merge-demo（开发主目录）+ CertAgent/demo 变体
│
├── 输入样例/                      ← 真实清单与样例输入
├── 输出示例/                      ← 完整整合产物（samples/expected_outputs + 真实运行产物）
│
├── 需求与设计文档/                ← PRD / 需求 / 实现思路 / 功能说明 / 经验总结 / 项目梳理
├── 拓展设计与原型/                ← OCR/网络/飞书设计稿 + parser 解析路线原型
└── 工作日志与周报/                ← 开发日志 / 周报 / 半月报 / 部署经验 / 版本说明合集
```

---

## 3. 两个版本怎么看（服务器版 vs 本地开发版，单独存放）

| | `服务器版/` | `本地开发版/` |
|---|---|---|
| 来源 | `CertAgent/Linux/` | `list-merge-demo/`（开发主目录）+ `_变体_CertAgent-demo/` |
| 角色 | 生产部署版（Linux + nginx 子路径 + systemd） | 日常开发调试 |
| 独有内容 | `compare_core/decrypt.py` 解密集成、`deploy/` 部署脚本、`BLUEPRINT.md`、`DOCS.md`、`.env.example`（含完整配置项） | `samples/` 自带样例、`项目说明_交接.md`（本项目最详交接说明）、`问题排查日志.md`、`test_diff_diag.py`、`test_llm.py` |
| Git 远程 | `Full-Stack-Frontend/Hisense/Agents/AI_Applications/CertAgent.git` | 独立 GitLab 远程 |

**两版本核心引擎/编排/Web/前端代码完全一致**，差异仅在环境特性（解密服务对接、部署资产）。不存在缺功能，差异都是合理的环境差异。

> ⚠️ 复制说明：本交接包是**快照复制**，原 Git 仓库（`CertAgent/`、`list-merge-demo/`）保持不动、历史与远程关联不受影响。
> 排除项：`.git/` `node_modules/` `__pycache__/` `runs/`（运行产物）已排除；`.env`（真实密钥）已排除，统一用 `.env.example` 代替。

### 快速启动任一版本
```bash
pip install -r requirements.txt
cp .env.example .env        # 用 llm 模式时填写 LLM_*（聚好看网关需 LLM_USER_KEY）

# CLI 冒烟（无需 Word/LLM）
python cli.py --orig-json fixtures/orig.json --plm-json fixtures/plm.json --out runs/out

# 真实 doc + 真 LLM
python cli.py --orig "原报告清单.doc" --plm "PLM导出清单.doc" --out runs/out --mode llm

# Web 服务
python -m webapi            # 后端 :8000
cd frontend && npm install && npm run dev   # 前端 :3000，默认 admin/admin
```

---

## 4. 架构（分层，依赖单向）

```
CLI(cli.py) / Web(webapi) → 编排层 graph/(LangGraph,可选) → 核心引擎 compare_core/(独立可单跑)
                                                            解析 → 判断(diff) → 建议(规则+LLM) → 写Word → 记忆
```

- **核心引擎 `compare_core/`** 不依赖 LangGraph，可 CLI 直接跑（默认）。
- **`graph/`** 用 LangGraph + `interrupt` 实现人在环（`--engine graph`）。
- **`webapi/`** FastAPI Web 服务，前端确认页人工决策。
- **`frontend/`** Vite + React，确认页 ReviewPage。

核心引擎子模块（两版本均有）：
| 子模块 | 职责 |
|---|---|
| `parser/` | .doc→.docx 转换（Word COM / LibreOffice）+ 表格解析（容错重心：合并单元格、列错位、非法字符清洗） |
| `differ/` | 归一化 + 匹配键对齐 + 差异分类 + 置信度 + 决策解析(resolve) + 审计 |
| `rules/` | 正向规则 + 反向规则（误报防护，YAML） |
| `suggester/` | 建议：规则化动作 + LLM/mock 变更项归纳 |
| `writer/` | 生成整合清单 + 对照表 docx（批注/高亮） |
| `memory/` | 决策落盘 + 指纹聚合读回 + 反哺建议（详见 `记忆库说明.md`） |

里程碑：M1 解析 · M2 diff · M3 编排出整合清单 · M4 人确认 · M5 LLM 对照表 · M6 记忆闭环

---

## 5. 输入 / 输出

### 输入（两份 Word 清单）
- A = 原始/旧版本清单（原报告清单，人工已整理）
- B = PLM 新品/新版本清单（PLM 导出清单）
- 支持 `.doc` / `.docx` / `.json` 三种输入；`.doc` 自动转 `.docx`（Windows 用 Word COM，Linux 用 LibreOffice）
  > ⚠️ **服务器版只接受 `.docx`/`.json`，拒绝 `.doc` 上传**（LibreOffice 在 systemd 下不可靠）。详见 `工作日志与周报/部署与使用指南.md`。

**输入格式要求（表头/表格结构/字段要求，不满足会解析失败）详见 `数据结构与实现思路详解.md` 的「第一部分补充：输入格式要求」**——这是接手必读，包含：
- 表头别名表（`HEADER_MAP`，哪些表头写法能识别）
- 表1/表2 编号规则与证书号取值逻辑
- 合并单元格/分组标题行/跨行填充的容错处理
- 匹配键（`关键件名称`+`型号`）与比对字段
- 不满足要求的后果对照表

详见 `输入样例/`。

### 输出
- **整合版关键件清单.docx**（合并后的完整清单）
- **变更前后对照表.docx**（逐项差异对照，含批注/高亮）
- 运行产物 JSON（diff/changes/group_diffs/suggestions/audit，便于追溯）

详见 `输出示例/`。

---

## 6. 数据保存（全文件系统，无数据库）

| 数据 | 格式 | 位置 |
|---|---|---|
| 正向/反向规则 | YAML | `compare_core/rules/data/` |
| 长期记忆（决策+理由） | JSONL | `runs/feedback.jsonl` |
| 使用统计 | JSONL | `runs/analytics.jsonl` |
| 运行产物 | docx/JSON | `runs/*/` |

> 注：交接包已排除 `runs/` 目录；如需历史运行产物见 `输出示例/真实运行产物_result目录/` 或原仓库 `list-merge-demo/runs/`。

---

## 7. 拓展方向

后续拓展（OCR 图片对比 / 网络信息库输入 / 飞书差异派单）**设计稿 + 解析路线原型**已归集到 `拓展设计与原型/`。其中设计为规划稿（未实现）、parser 原型为已跑过的选型实验。详见 `拓展设计与原型/README.md`。

---

## 8. 关键文档导航

| 想了解 | 看这里 |
|---|---|
| **整体实现思路 + 数据结构设计** | **`数据结构与实现思路详解.md`**（集中讲透，推荐先读） |
| 项目最详交接说明 | `本地开发版/项目说明_交接.md` |
| 实现思路完整版 | `需求与设计文档/实现思路_变更清单整合Demo.md`（198行11节，含pdf-reviewer借鉴/数据流/置信度/规则库/反馈闭环/里程碑） |
| 数据模型代码 | `本地开发版/compare_core/models.py`（Row/DiffItem/GroupDiff/Suggestion/AuditReport 等定义） |
| 记忆库字段与机制 | `本地开发版/记忆库说明.md` |
| 项目原则与文档路由 | `服务器版/BLUEPRINT.md` `服务器版/DOCS.md` |
| 需求与实现思路 | `需求与设计文档/需求说明_变更开发清单整合.md` `需求与设计文档/实现思路_变更清单整合Demo.md` |
| 功能说明 | `需求与设计文档/认证智能体项目功能说明.md` |
| 经验总结 | `需求与设计文档/认证智能体项目经验总结.md` `工作日志与周报/认证智能体项目经验总结.md` |
| 项目整体梳理 | `需求与设计文档/项目整体梳理.md` |
| PRD 原文 | `需求与设计文档/20.认证智能体PRD.md`（+ `PRD图片和附件/`、PDF） |
| 部署经验 | `工作日志与周报/部署与使用指南.md` `工作日志与周报/部署与Nginx子路径排查经验.md` `工作日志与周报/部署问题排查日志.md` |
| 开发历程 | `工作日志与周报/开发历程_版本说明合集/`（12 个版本说明） |
| 记忆库机制 | `服务器版/记忆库说明.md` 或 `本地开发版/记忆库说明.md` |

---

## 9. 与项目二的边界

本项目（项目一）做**清单整合**；工作区另有一个项目二"报告草稿准确性核对（ReportVerify）"，做**核对**。两者边界见 `需求与设计文档/两个项目导读.md`。本交接包**只含项目一**，项目二相关目录（`报告草稿准确性核对/` `确认报告草稿/` `确认报告草稿样本/` `report-verify-demo/`）未纳入。
