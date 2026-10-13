# 项目二 · 报告草稿准确性核对（ReportVerify）· 交接包

> 本交接包汇集项目二（报告草稿准确性核对）的全部资产，集中在一个文件夹用于交接。
> 项目二与项目一（认证清单整合）的边界见 `需求与设计文档/两个项目导读.md`；项目二自带最详交接说明见 `主代码/交接文档.md`。
> 打包时间：2026-09-03

---

## 1. 这个项目做什么

核对两份 Word 文档，产出"哪里对不上"的证据：

- **CERT 认证资料**（应然基准，超集）：多表文档，含安全清单、EMC 清单、变更确认表、产品描述，还有图片、声明页等。文件名以 `A20` 开头。
- **DRAFT 报告草稿**（实然对象，被核对、被批注）：相对规整的关键件清单。文件名以 `100` 开头。
- **输出**：① 批注版 DRAFT（差异批注写在报告草稿对应单元格）；② 编号差异汇总 docx（1、2、3… 连续编号，含 CERT 值 / DRAFT 值 / 差异类型 / 位置）。

> ⚠️ **输入格式要求（接手必读）**：CERT/DRAFT 必须是含表格的 Word 文档（`.docx` 首选，`.doc` 自动转换），方向不可交换。表格首行表头需命中 `ALIASES` 别名（尤其 `关键件名称`+`型号`），清单类子块靠表头指纹自动分类（安全/EMC/变更/产品描述），不命中的表进未识别提示人工复核。**详细要求（表头别名表、子块指纹判定、归一化规则、不满足后果）见 `数据结构与实现思路详解.md` 的「第一部分补充：输入格式要求」**。

关键动词是**核对**（不是"合并/整合"——整合是项目一做的事）。

**核心边界**（贯穿全项目）：
1. **确定性核对优先**：是否"有差异"由严格逐字段比较决定，规则带版本号、可回放。
2. **LLM 仅辅助**：只做"候选匹配"和"差异解释"，只读参考，**不改变确定性结论、不改变下载门禁**。
3. **人工确认 + 下载门禁不可绕过**：全部差异人工确认前，禁止下载最终文档。
4. CERT 是应然值、DRAFT 是实然值，方向不可交换；批注只能落在 DRAFT。
5. 本项目独立于项目一（CertAgent），复用其解析/模型/网关凭据思路，但不修改 CertAgent 生产代码。

状态：**P0–P5 已完成、LLM 集成完成并真实验证、前端重写完成**；P6 分专业路由、P7 多轮审批**已设计未实现**（待业务确认）。

---

## 2. 交接包目录结构

```
报告草稿核对_交接包/
├── README_交接总览.md            ← 本文件（总入口）
├── 数据结构与实现思路详解.md      ← 集中讲透整体实现思路 + 全部数据结构（推荐先读）
│
├── 主代码/                        ← 报告草稿准确性核对/（核心代码库,排除产物/密钥）
├── 早期Demo/                      ← report-verify-demo/（初版简化Demo,可选参考）
│
├── 输入样本/                      ← CERT/DRAFT 真实样本(141MB CERT + DRAFT + 转换)
├── 输出示例/                      ← 完整核对产物(批注版DRAFT + 差异汇总 + verification.json)
│
├── 需求与设计文档/                ← 交接文档/design/tasks/可行性方案/LLM门禁/大模型接口说明
└── 工作日志/                      ← 确认报告草稿工作日志 + 周报/半月报
```

---

## 3. 主代码怎么看

主代码 `主代码/` 来自工作区 `报告草稿准确性核对/`，是项目二的核心代码库。

```
主代码/
├── 交接文档.md               ← 项目二最详尽交接说明（314行,推荐先读）
├── README.md / design.md / tasks.md / LLM_RELEASE_GATE.md / 交付清单.md
├── cli.py                    命令行入口
├── report_verify/            核对核心包
│   ├── pipeline.py           编排:定位→解析→核对→批注→汇总→一致性校验
│   ├── document_parser.py    通用 docx 解析
│   ├── draft_parser.py       DRAFT 清单解析 + 批注锚点
│   ├── cert_locator.py       CERT 超集按表头指纹定位目标子块
│   ├── field_map.py          CERT/DRAFT 表头别名与字段映射
│   ├── rules.py              归一化规则加载/应用
│   ├── verify_differ.py      逐字段核对,产出 VerifyDiff/RowDiff
│   ├── comment_writer.py     批注版 DRAFT writer(锚点失败降级)
│   ├── summary_writer.py     编号差异汇总 writer
│   ├── review.py             人工确认/反馈记忆落盘与回放
│   ├── validation.py         双输出一致性校验
│   ├── models.py             数据模型(Anchor/DocumentRow/LocatedBlock/VerifyDiff/RowDiff/VerifyResult)
│   ├── converter.py          .doc→.docx 转换
│   ├── env_bootstrap.py      启动时加载.env
│   ├── llm_injection_check.py 提示注入/越权检查
│   └── llm/                  可选 LLM 子包(config/policy/jobmode/client/circuit/evidence/explain/orchestrator/discipline/recheck/schemas/release_gate)
├── webapi/                   FastAPI(上传/进度/行级差异/确认/下载/LLM证据)
├── frontend/index.html       单文件前端(三视图+AI只读区+实时计时)
├── rules/normalization.json  归一化规则配置(版本化)
├── samples/                  内置样本(data/expected_outputs/manifest/gold_baseline)
├── docs/                     背景文档 + specs/(两套完整spec副本)
├── scripts/                  一键脚本(run_web/run_sample/run_tests/check_llm)
└── tests/                    标准库unittest(357项,核对核心+LLM子包+Web)
```

> 排除说明：复制自原仓库，已排除 `.git/ __pycache__/ runs/`；`.env`（真实密钥）已排除，用 `.env.example` 代替。

---

## 4. 快速启动

```powershell
# 推荐：一键脚本（见 scripts/README.md）
.\scripts\run_web.ps1       # 启动服务（自动清理残留 LLM 环境变量）
.\scripts\run_sample.ps1    # 用内置样本跑一次完整核对
.\scripts\run_tests.ps1     # 全量测试（357 项）
.\scripts\check_llm.ps1     # LLM 配置自检 + 发布门禁

# 等价原始指令
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v          # 测试应全通过
uvicorn webapi.app:app --host 0.0.0.0 --port 8010 # 启动 Web,浏览器开 http://127.0.0.1:8010/

# 命令行一次性核对
python cli.py --cert <CERT.docx> --draft <DRAFT.docx> --out runs\myrun
```

环境变量：复制 `.env.example` 为 `.env` 填凭据（真实网关地址与密钥只在 `.env`，已 gitignore）。启动前若父 shell 残留 `REPORT_VERIFY_LLM_*`，先 `Remove-Item Env:REPORT_VERIFY_LLM_*`。

---

## 5. 处理流程（确定性主链）

```
CERT 超集 ──→ converter(.doc→.docx) ──→ document_parser ──→ cert_locator ─┐
                                                        （表头指纹定位子块）│
DRAFT 清单 ──→ converter ─→ document_parser ──→ draft_parser ──────────────┤
                                               （保存批注锚点）             │
                                                                           ▼
           field_map（字段映射）──→ rules（归一化）──→ verify_differ（逐字段核对）
                                                              │
                                          ┌───────────────────┼───────────────────┐
                                          ▼                   ▼                   ▼
                                 comment_writer        summary_writer       （可选）llm 子包
                                 批注版 DRAFT           编号差异汇总          候选/解释 只读证据
                                          └─────── validation 一致性校验 ───────┘
                                                              │
                                              review 人工确认 + 下载门禁
```

要点：
- **定位不漏**：CERT 未识别的表进 unrecognized 元数据提示人工复核，不静默丢弃。
- **锚点降级**：批注优先落差异字段单元格，失败退到行/单元格首段；再失败则只进汇总并标注"批注锚点失败"，绝不生成假的"无差异"。
- **可追溯**：每个差异有稳定 `key` 与 `sig`，可反查 CERT 表/行/字段 ↔ DRAFT 表/行/字段。

---

## 6. 核对规则（判定口径）

规则文件：`rules/normalization.json`，版本 `normalized-v2`。原文仅用于展示，**归一化值只用于判断**。LLM 不得擅自扩大忽略范围。

默认启用的归一化项：`trim_outer_space`（首尾空白）、`collapse_whitespace`（连续空白）、`casefold`（大小写）、`fullwidth_ascii`（全半角）、`wave_dash`（波浪线归一）、`list_separator`（分隔符等价，顺序仍敏感）、`strip_all_space`（内部空白，标准号/型号空格）、`placeholder_blank`（`/`、`-`、`N/A` 视为空）。

**仍判差异的实质字符差异**：证书号、型号、规格数值、位号、制造商、生产企业、认证标准、备注、变更前后值等。

---

## 7. LLM 集成（可选、只读辅助）

- 代码在 `report_verify/llm/`，完整 spec 在 `主代码/docs/specs/report-draft-llm-integration/`，接口形态/鉴权/协议见 `需求与设计文档/大模型接口说明.md`。
- 生产默认 `MODE=off`。两种能力：**candidate**（候选匹配，跨文档可能是同一项）、**explain**（差异解释）。
- 启用前跑发布门禁：`python -m report_verify.llm.release_gate`（退出码 0=安全）。
- **最小回滚**：配置切回 `REPORT_VERIFY_LLM_MODE=off` 并重启。回滚不需要复制/轮换 key。

---

## 8. 数据保存（全文件系统，无数据库）

| 数据 | 格式 | 位置 |
|---|---|---|
| 归一化规则 | JSON（版本化） | `rules/normalization.json` |
| LLM 配置 | `.env`（gitignore） | `REPORT_VERIFY_LLM_*` |
| 运行产物 | docx/JSON | `runs/<任务id或时间戳>/`（已排除） |
| LLM 脱敏证据 | JSON sidecar | `runs/.../llm-evidence.json`（已排除） |
| 任务记录 | JSON | `runs/web_jobs/<job_id>/job.json`（已排除） |

> 完整数据结构设计（数据模型字段表、记录结构、流转关系）见 `数据结构与实现思路详解.md`。

---

## 9. 关键文档导航

| 想了解 | 看这里 |
|---|---|
| **整体实现思路 + 数据结构设计** | **`数据结构与实现思路详解.md`**（集中讲透，推荐先读） |
| 项目二最详交接说明 | `主代码/交接文档.md`（314行，功能/架构/目录/流程/规则/LLM/已实现/未实现/API/排错） |
| 任务分解与状态 | `主代码/tasks.md`（P0–P7，已实现/BLOCKED/未实现） |
| 设计摘要 | `主代码/design.md`（架构/数据模型/正确性属性） |
| LLM 发布门禁 | `主代码/LLM_RELEASE_GATE.md` |
| LLM 接口说明 | `需求与设计文档/大模型接口说明.md` |
| 完整 spec | `主代码/docs/specs/`（report-draft-verify + report-draft-llm-integration） |
| 可行性方案 | `需求与设计文档/报告草稿准确性核对_可行性方案.md` |
| 早期 Demo | `早期Demo/`（report-verify-demo 初版，可选参考） |

---

## 10. 已实现 vs 未实现（接手重点）

**已实现**（P0–P5 + LLM）：
- 基线/PoC/骨架、两侧解析、核对引擎、双文档输出、CLI/测试/确认、Web 独立接入
- LLM 集成（30 个必需任务，真实网关验证通过）、前端重写、差异解释分批+并发、任务计时

**已设计未实现**：
- **P6 分专业路由**（BLOCKED）：数据结构与配置接口已定义，但所有差异恒为 `discipline_pending`，待业务确认划分规则
- **P7 多轮审批闭环**：T26 审批状态机、T27 轮次版本对比、T28 KOA/Tims 集成
- **候选阈值语义优化**（建议最先做）：现"整批否决"改为"逐条丢弃"
- **金标准升级**：`gold_baseline.json` 是结构基线非业务金标准

详见 `主代码/交接文档.md` 第 8 节。

---

## 11. 与项目一的关系（接手必读）

**项目二（报告草稿核对）是基于项目一的逻辑，在"报告草稿核对"这一新场景下的应用**。

### 复用项目一的内核

项目二沿用了项目一"认证清单整合"沉淀下来的**确定性核对内核**：
- **Word 表格结构化解析**：底层表格遍历思路一脉相承（项目二 `document_parser.py` 底层沿用项目一 list-merge-demo 的 grid/table 思路），同样处理合并单元格、分组标题、跨行填充、表头别名映射。
- **匹配键对齐 + 逐字段差异**：项目一"关键件名称+型号"匹配、归一化后逐字段比对的逻辑，被项目二继承为 CERT/DRAFT 两侧对齐 + 逐字段核对。
- **确定性优先 + 人在环确认**：项目一"规则判定差异、人工确认、LLM 只做建议"的原则，项目二完全沿用（确定性核对 + 人工确认 + 下载门禁 + LLM 只读辅助）。

### 新场景的改造（与项目一的不同）

项目一把"两份清单整合成一份"（合并去重 + 标注新增/差异 → 整合清单 + 对照表）；项目二把"CERT 超集 vs DRAFT 草稿"核对出"哪里对不上"（**不合并、只批注 + 编号汇总**）。因此项目二相对项目一新增了：
- **表头指纹子块定位**（`cert_locator`）：CERT 是多表超集，按表头指纹自动分出安全清单/EMC清单/变更确认表/产品描述四类子块，未识别的表提示人工复核（定位不漏）。
- **DRAFT 批注锚点**（`draft_parser`）：核对差异要写回 DRAFT 原位，锚点降级（字段→行→首段→汇总兜底），绝不生成假"无差异"。
- **CERT/DRAFT 方向不可交换**：`cert_value` 永远应然、`draft_value` 永远实然，批注只落 DRAFT。
- **双输出一致性校验**（`validation`）：批注版 DRAFT 与编号汇总的差异数/方向/锚点归属必须一致，不漏不重。

### 代码关系

项目二是**独立代码库**（`报告草稿准确性核对/`），不依赖项目一运行时，但设计思想上继承项目一的"先结构化、后智能化、确定性优先、人在环确认"。两者代码各自独立、可分别部署。

> 一句话：项目一是"把两份清单合成一份"的整合工具，项目二是"拿 CERT 基准核对 DRAFT 草稿"的核对工具——**同一个确定性核对内核，两个不同业务场景的应用**。
