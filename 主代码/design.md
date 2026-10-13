# Design: 报告草稿准确性核对

> 独立项目设计摘要。完整设计基线见 `.kiro/specs/report-draft-verify/design.md`。

## Overview

本项目核对认证资料超集（CERT）与相对规整的报告草稿（DRAFT）。CERT 是应然基准，DRAFT 是被核对对象，批注写入 DRAFT。安全清单、EMC 清单、变更确认表、产品描述关键字段全部纳入 MVP。

### 文档角色

```text
CERT 认证资料超集（多表、图片、声明页）
  └─ 定位：安全清单 / EMC 清单 / 变更确认表 / 产品描述关键字段

DRAFT 报告草稿（规整关键件清单）
  └─ 解析并保存表格锚点

CERT 应然值 + DRAFT 实然值
  └─ 字段级逐字核对 → 批注版 DRAFT + 编号差异汇总
```

### 核对规则

- 全部目标子块都核对；
- 默认忽略外层空白、连续空白、大小写、全半角和明确等价波浪线；
- 证书号、规格数值、型号、制造商、生产企业、认证标准、备注和变更前后值等实质字符差异仍纳入核对；
- 规则带版本号，可通过 `enabled` 显式配置；原文用于展示，归一化值只用于判断；LLM 不得擅自扩大忽略范围。

## Architecture

```text
CERT 超集 ── parse + cert_locator ─┐
                                  ├─ align ─ diff ─ classify ─ human_review
DRAFT 清单 ── parse + anchors ────┘                         │
                                                           ├─ comment_writer → 批注版 DRAFT
                                                           └─ summary_writer  → 差异汇总
```

独立项目只复用 CertAgent 的解析、规则、差异、批注和 Web 资产，不直接修改 CertAgent 生产代码或部署配置。

## Components and Interfaces

- `cert_locator`：在 CERT 超集内按表头指纹定位目标子块；图片页、声明页和未识别表保留元数据。
- `draft_parser`：解析 DRAFT 规整清单并保存 `table_idx / row_idx / cell_idx / para_hint`。
- `verify_differ`：以 CERT 为应然基准，输出字段不一致、DRAFT 漏项、DRAFT 多项。
- `comment_writer`：将批注写到 DRAFT 的单元格/段落；锚点失败时降级并由汇总兜底。
- `summary_writer`：按 1、2、3 连续编号输出 CERT 值、DRAFT 值、差异类型和位置。
- `discipline_router`：本阶段只定义配置接口和 pending 状态，不自动分配、不部署。

## Data Models

```python
VerifyDiff(
    key, block_type, item_name, diff_type, field,
    cert_value, draft_value, anchor,
    discipline=None, discipline_status="pending", rule_version=None
)
```

专业路由预留电路、电源、模组光学、结构、认证、产品线总经理，允许未来多专业关联。划分规则确定前，所有差异保持 `discipline_pending`，不触发审批。

## Correctness Properties

### Property 1: 不漏差异
每个差异至少出现在批注版 DRAFT 或差异汇总中。
**Validates: Requirements 3.1, 4.1**

### Property 2: 批注对象正确
批注锚点必须指向 DRAFT，不得指向 CERT。
**Validates: Requirements 3.2**

### Property 3: 基准方向正确
`cert_value` 始终是应然值，`draft_value` 始终是实然值。
**Validates: Requirements 2.1**

### Property 4: 逐字核对边界明确
只有已配置的无意义差异判一致，其他字符差异必须保留。
**Validates: Requirements 1.1**

### Property 5: 定位结果可追溯
未识别 CERT 子块必须提示人工复核，不得静默丢弃。
**Validates: Requirements 1.2**

## Error Handling

解析失败、子块未识别、字段无法映射、批注锚点失败和加密/不支持格式均需显式记录。批注失败时汇总文档必须保留差异，禁止静默生成“无差异”结果。

## Testing Strategy

先做批注 PoC，再做定位单测、字段核对单测、真实样本回归、双输出一致性校验和人工金标准验收。分专业路由和多轮审批在规则确认后另行测试。
