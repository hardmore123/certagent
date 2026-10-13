# 设计文档：报告草稿准确性核对（ReportVerify）

> 独立新项目，复用 CertAgent / list-merge-demo 的 `compare_core` 解析与比对资产。
> 对应业务需求：**确认报告草稿准确性**（全产品线、各专业确认）。
> 本设计只覆盖 MVP（定位 → 比对 → 输出两份），分专业路由与多轮审批闭环列为后续阶段。

## Overview

### 目标

自动比对**海信认证资料**与**认证机构报告草稿**，找出不一致的差异点，并产出两份可直接进入审批流程的文档：

1. **批注版报告草稿**：在报告草稿原文的差异位置插入 Word 批注，供发回认证机构修改；
2. **差异汇总文档**：按 1、2、3 编号列出全部差异项，供各专业审批人确认。

### 核心认知（区别于“整篇文字对比”）

本任务不是把两个 Word 全文做文本 diff，而是**结构化子块的字段级核对**，分三步：

1. **定位**：从报告草稿中用表头指纹识别出与认证资料同类的子块（安全关键件清单、EMC 清单、变更确认表、产品描述关键字段）；
2. **比对**：将两侧定位到的子块做字段级比对，输出差异点（项、A 值、B 值、差异类型）；
3. **输出**：生成批注版报告草稿 + 编号差异汇总。

### 两侧文档角色（已确认，2026-08-28）

| 记号 | 业务名称 | 结构 | 角色 |
|---|---|---|---|
| CERT | 海信认证资料 | 超集：完整报告，多表混排 + 照片 + 声明页 | **基准（应然值），需先定位子块** |
| DRAFT | 认证机构报告草稿 | 相对规整的关键件清单（表格为主） | **被核对对象，批注打在它上面** |

关键含义：

- **需要“表头指纹定位”的是认证资料（CERT 超集）**：它是多表混排带照片声明页的那份，关键件清单是其内嵌子块，必须先定位抽取；
- **报告草稿（DRAFT）是规整清单，可直接解析**；
- **批注打在报告草稿（DRAFT）上**，因为它最终要发回认证机构修改；
- **基准方向**：以认证资料（CERT）为应然值，核对报告草稿（DRAFT）是否与之一致。

### 与现有清单整合项目的本质差异

| 维度 | 清单整合（CertAgent 已有） | 报告草稿核对（本项目） |
|---|---|---|
| 输入 | 两份同类关键件清单 | 一份规整清单 + 一份报告超集（异类） |
| 关键新增 | — | 报告结构解析（多表分类定位）、Word 批注写入 |
| 语义 | 合并 + 变更归纳 | 一致性核对（应然 vs 实然） |
| 输出 | 整合清单 + 变更对照表 | 批注版报告草稿 + 差异汇总 |
| 匹配基准 | PLM 为变更后基底 | 认证资料（CERT 超集）为应然基准 |
| 定位对象 | — | 认证资料（CERT 超集）需多表分类定位 |
| 批注对象 | — | 报告草稿（DRAFT 规整清单） |

### 范围

**MVP（本设计实现）**：上传认证资料（CERT）与报告草稿（DRAFT）；对认证资料（超集）做多表分类与子块定位；CERT/DRAFT 字段级比对输出差异集；生成批注版报告草稿；生成编号差异汇总；Web 上传 / 任务 / 确认 / 下载（复用现有框架）。**核对范围：全部子块都要核对**（安全关键件清单 + EMC 关键件清单 + 变更确认表 + 产品描述关键字段）。

**后续阶段（仅预留接口，不实现）**：

- **P-A 分专业路由**：差异项按专业（电路 / 电源 / 模组光学 / 结构 / 认证 / 产品线总经理）分类路由；
- **P-B 多轮审批闭环**：草稿 → 各专业审批 → 认证工程师汇总发机构 → 机构改完 → 二次审批，循环到完成（审批状态机 + 轮次版本对比）；
- **P-C KOA/Tims 流程集成**。

设计原则：MVP 数据模型**预留**后续字段（专业标签、轮次、审批状态），避免返工，但不实现流转逻辑。

## Architecture

```text
                    ┌────────────────────────────────────────────────────┐
上传 CERT(认证资料超集)─┤   report_verify pipeline（LangGraph 编排）          │
上传 DRAFT(报告草稿清单)─┤                                                    │
                    │  parse+locate(CERT 超集 多表分类定位) ─┐               │
                    │                                        ├─► align ─► diff ─► classify
                    │  parse(DRAFT 规整清单，记批注锚点) ─────┘               │        │
                    │                                                    │        ▼
                    │                          human_review ◄─────────────────  差异集
                    │                                │                            │
                    └────────────────────────────────┼────────────────────────────┘
                                                      ▼
                          ┌──────────────────────┬──────────────────────┐
                          ▼                       ▼                      ▼
                批注版报告草稿.docx        差异汇总.docx(1/2/3)     反馈记忆(JSONL)
                (comment_writer 新增,      (summary_writer 复用改造)  (memory 复用)
                 批注锚点指向 DRAFT)
```

### 复用与新增边界

| 模块 | 处理 | 说明 |
|---|---|---|
| `parser/converter`、`parser/docx_parser` | 复用 | A 解析与清单解析沿用；docx 走 python-docx |
| `differ`（归一化 / 匹配键 / 分类 / 置信度） | 复用 + 微调 | 核对语义调整匹配键与字段权重 |
| `rules`（正 / 反向规则） | 复用 | 抑制空格 / 全半角 / 单位等无意义差异 |
| `memory` | 复用 | 差异确认反馈落盘与反哺 |
| `webapi` + `frontend` | 复用 | 新增“核对任务”类型与确认页 |
| `report_locator` | **新增** | 报告多表分类 + 目标子块定位 |
| `verify_differ` | **新增（薄封装）** | 以 A 为基准的一致性核对语义 |
| `comment_writer` | **新增** | python-docx `add_comment` 写批注到 B |
| `summary_writer` | 复用改造 | 编号差异汇总，来自现有 writer |

### pipeline 编排

节点：`parse_locate_cert → parse_draft → align → diff → classify → human_review → write(批注+汇总) → memory`。其中 `parse_locate_cert` 对认证资料超集做多表定位，`parse_draft` 解析报告草稿并记批注锚点。`human_review` 用 LangGraph interrupt 实现人在环，与现有清单整合一致。

## Components and Interfaces

### cert_locator（认证资料结构定位，新增）

职责：把**认证资料 CERT（超集）**的多张表按表头指纹分类，抽取目标子块（安全清单 / EMC 清单 / 变更确认表 / 产品描述），过滤照片页与声明页。

```python
def locate_cert_blocks(docx_path: str) -> LocatedCert:
    """
    对认证资料超集返回定位结果：
      - blocks: List[Block]（安全清单 / EMC 清单 / 变更确认表 / 产品描述）
      - unrecognized: 未命中指纹的表，提示人工复核，不丢弃
    """
```

> 报告草稿 DRAFT 是规整清单，直接用 `docx_parser` 解析即可；解析时**为每个数据单元格记录批注锚点**（table_idx / row_idx / cell_idx / para_hint），供 comment_writer 使用。

表头指纹路由规则（可配置、可扩展）：

| 子块类型 | 表头指纹（首行包含） |
|---|---|
| 安全关键件清单 | 序号 + 关键件名称 + 型号 + 认证标准 |
| EMC 关键件清单 | 序号 + 关键件名称 + 型号（EMC 段） |
| 变更确认表 | 序号和名称 + 变更前 + 变更后 |
| 产品描述关键字段 | 型号 / 额定值等关键字段（键值形式） |

未命中的表标记为 `unrecognized`，在结果中提示人工复核，不静默丢弃。

### verify_differ（核对比对，新增薄封装）

复用 `compare_core.differ`，语义从“变更归纳”改为“**以认证资料 CERT 为应然基准的一致性核对**”：

```python
def verify(cert_block: Block, draft_block: Block, rules) -> list[VerifyDiff]:
    """
    对齐 CERT、DRAFT 子块后，逐字段比对：
      - MATCH：一致
      - FIELD_MISMATCH：同一项、某字段不一致（认证资料值 / 报告草稿值）
      - MISSING_IN_DRAFT：认证资料有、报告草稿无（报告漏项）
      - EXTRA_IN_DRAFT：报告草稿有、认证资料无（报告多项）
    """
```

匹配键沿用已确认规则：`表号 + 分组 + 关键件名称 + 型号 + 位号 + 规格材料 + 证书号`（rich）与 `表号 + 分组 + 名称 + 型号`（loose）。

### comment_writer（批注写入，新增，最关键）

已实测：`python-docx 1.2.0` 原生支持 `Document.add_comment(runs, text, author, initials)`，无需 Word COM / 手改 OOXML。

```python
def write_comments(draft_docx_path: str, diffs: list[VerifyDiff], out_path: str, author="ReportVerify"):
    """
    对每条差异，回到报告草稿 DRAFT 的 anchor（table/row/cell 段落 runs）上 add_comment。
    锚点失败时退化为：单元格首段批注；仍失败则仅进汇总文档，保证不漏项。
    """
```

批注文案模板（示例）：`[差异] 认证资料为「CERT值」，报告草稿为「DRAFT值」（类型：字段不一致）`。

### summary_writer（差异汇总，复用改造）

复用现有 writer 生成机制，输出编号汇总：

| 序号 | 差异项 | 认证资料(CERT，应然) | 报告草稿(DRAFT，实然) | 差异类型 | 专业(预留) | 建议 |
|---|---|---|---|---|---|---|

### 分专业路由（本阶段只设计，不部署）

差异项 → 专业的映射规则暂未由业务确认，因此本阶段只设计数据结构、配置入口和待确认流程，**不自动分配专业、不触发审批、不部署路由**。

预留设计：

- 规则表：按 `关键件名称 / 子块类型 / 分组 / 字段` 映射到电路、电源、模组光学、结构、认证、产品线总经理等角色；
- 规则版本：记录规则版本、制定人、生效时间和适用产品线，便于规则变更追溯；
- 未命中项：状态为 `discipline_pending`，进入认证工程师人工分配队列，不由 LLM 直接决定最终路由；
- 多专业项：允许一个差异项关联多个专业；
- 产品线总经理：作为汇总/升级审批角色，不与某一具体技术字段硬绑定；
- 规则确定后，再启用 `discipline` 填充、按专业分节输出和审批接口；
- LLM 只能提供候选专业建议并保留理由，不能绕过已发布的业务规则。

### 多轮审批闭环（后续，仅预留设计）

- **审批状态机**：`草稿录入 → 各专业审批 → 认证工程师汇总 → 发机构修改 → 机构回稿 → 二次审批 → 完成`；
- **轮次版本对比**：保存每轮 B 版本，第 N+1 轮回稿与第 N 轮差异项做“修改项闭合度”核对（已改 / 未改 / 改错）；
- **KOA/Tims 集成**：附件上传与审批意见回填，作为外部接口，不与核对内核耦合。

## Data Models

```python
class Anchor(BaseModel):
    table_idx: int
    row_idx: int
    cell_idx: int | None = None      # None 表示锚到整行
    para_hint: str | None = None     # 定位用的文本片段，兜底重定位
    # 注意：anchor 恒指向报告草稿 DRAFT（批注对象），不指向认证资料 CERT

class VerifyDiff(BaseModel):
    key: str                          # 全局唯一，如 verify-12
    block_type: str                   # 安全清单 / EMC / 变更确认表 / 产品描述
    item_name: str                    # 关键件名称或字段名
    diff_type: str                    # match / field_mismatch / missing_in_draft / extra_in_draft
    field: str | None = None          # 不一致的字段名
    cert_value: str | None = None     # 认证资料应然值（基准）
    draft_value: str | None = None    # 报告草稿实然值（被核对）
    anchor: Anchor | None = None      # 批注定位（指向报告草稿 DRAFT）
    discipline: str | None = None     # 预留：分专业路由标签
    confidence: float = 1.0
    sig: str                          # 记忆指纹：block|item|field
```

预留但 MVP 不填充：`discipline`（分专业）、`round_no`（审批轮次）、`approval_status`（审批状态）。

## Correctness Properties

> 说明：本项目采用设计优先，requirements.md 尚未建立。下方 `Validates` 编号暂用占位映射（1 比对、2 输出差异、3 批注标识、4 汇总标识、5 审批闭环），待 requirements.md 建立后回填为正式条目。

### Property 1: 不漏差异
每条 `VerifyDiff` 要么在批注版报告草稿中有批注，要么在差异汇总中有编号条目，二者至少其一。
**Validates: Requirements 3.1, 4.1**

### Property 2: 锚点指向报告草稿
所有批注锚点必须落在报告草稿 DRAFT 的文档对象上，不得写到认证资料 CERT。
**Validates: Requirements 3.2**

### Property 3: 基准方向恒定
`cert_value` 恒为认证资料应然值，`draft_value` 恒为报告草稿实然值，不得互换。
**Validates: Requirements 2.1**

### Property 4: 字段核对与无意义差异边界
字段内容默认采用已确认的格式归一化：外层空白、连续空白、大小写、全半角和明确等价符号不构成差异。规则有版本号且可配置；未配置的实质字符差异（证书号、规格数值、型号、制造商、生产企业等）仍必须保留，不能由模糊匹配掩盖。
**Validates: Requirements 1.1**

### Property 5: 未识别子块不丢弃
`unrecognized` 表必须在结果中显式提示，不得静默跳过。
**Validates: Requirements 1.2**

### Property 6: 编号连续唯一
差异汇总的 1、2、3 编号连续、无重复、与批注一一可追溯（通过 `key`）。
**Validates: Requirements 4.2**

## Error Handling

| 场景 | 处理 |
|---|---|
| 认证资料表未被指纹识别 | 标 `unrecognized`，提示人工复核，不丢弃 |
| 批注锚点定位失败 | 退化单元格首段批注 → 再失败仅进汇总，不漏项 |
| CERT/DRAFT 列名不一致 | 扩展 `HEADER_MAP`，人工确认页可纠正 |
| 无意义差异噪声 | 复用归一化 + 反向规则库过滤 |
| 加密 / .doc 文件 | 复用 CertAgent 三层处理（透明加密解密 / 密码加密手动 / .doc 另存为） |
| 大表性能 | python-docx 纯解析，必要时按表并行 |

## Testing Strategy

1. **批注 PoC（最先做）**：10~20 行伪造清单 + 精简报告，验证 add_comment 锚点正确、Word 可见（唯一不确定点，优先锁定）；
2. **定位单测**：各类表头指纹命中 / 未命中；
3. **核对单测**：field_mismatch / missing_in_b / extra_in_b 分类正确；
4. **真实样本回归**：用 `确认报告草稿样本/` 的 A、B 跑通端到端，产出两份文档；
5. **验收口径**：差异召回、字段一致率、批注定位成功率、无意义差异过滤率，人工金标准比对（不把字符串命中率当准确率）。

## 附录：目录结构（新项目独立文件夹）

```text
report-verify-demo/
├── compare_core/           # 复用（解析/differ/rules/memory/writer）
│   ├── cert_locator.py     # 新增：认证资料超集多表分类定位
│   ├── verify_differ.py    # 新增：核对语义薄封装
│   └── comment_writer.py   # 新增：Word 批注写入（写到报告草稿）
├── webapi/                 # 复用改造：新增核对任务类型
├── frontend/               # 复用改造：核对确认页
├── cli.py                  # 核对 CLI
├── runs/out/               # 批注版报告草稿 + 差异汇总产物
└── samples/                # 认证资料 + 报告草稿 真实样本
```

## 附录：实施顺序（阶段）

| 阶段 | 目标 | 交付 |
|---|---|---|
| P0 | 批注写入 PoC | 批注版 docx 跑通（锁定唯一不确定点） |
| P1 | cert_locator | 认证资料超集多表分类 + 目标子块定位 |
| P2 | verify_differ | CERT/DRAFT 字段级核对差异集 |
| P3 | 双输出 | 批注版报告 + 编号差异汇总 |
| P4 | Web 接入 | 上传 / 确认 / 下载端到端 |
| P5（后续） | 分专业路由 | discipline 分类 + 汇总分节 |
| P6（后续） | 多轮审批 | 状态机 + 轮次版本对比 |

## 附录：待确认清单

1. ~~**方向**~~ ✅ 已确认（2026-08-28）：认证资料=超集=基准（需定位子块）；报告草稿=规整清单=被核对=批注对象。
2. ~~**子块范围**~~ ✅ 已确认（2026-08-28）：全部子块都要核对（安全清单 + EMC + 变更确认表 + 产品描述关键字段）。
3. ~~**差异粒度**~~ ✅ 已确认（2026-08-28）：证书号、规格、型号、位号、制造商、生产企业、认证标准、备注、变更前/变更后和产品描述关键字段均逐字段核对；
4. **无意义差异边界**：默认忽略已确认的外层空白、连续空白、大小写、全半角和明确等价符号；规则带版本号且可回放。证书号、型号、规格数值、位号、生产企业等实质差异仍保留，其他归一化必须先写入规则配置；
5. **专业分类规则**：后续分专业路由的“关键件 → 专业”映射由谁定义？
6. **批注作者 / 文案规范**：批注署名与话术是否有公司统一要求？
7. **样本文件确认**：已固化 `samples/manifest.json`；当前样本确认 CERT 为超集、DRAFT 为规整清单。
