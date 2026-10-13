# 示例输出（samples/expected_outputs/）

本目录是用 `samples/data/` 样本跑一次确定性核对后的**真实产物示例**，供交接方在不运行程序时也能看到"输出长什么样"，以及作为回归参照。

来源：`runs/acceptance_2026-08-28/`（2026-08-28 验收运行，规则 `strict-v1`，`enabled=[]` 即纯逐字比较）。

| 文件 | 说明 |
|---|---|
| `verification.json` | 完整核对 trace（约 9MB）：输入路径、规则版本、CERT 定位子块、DRAFT 锚点、字段映射、归一化前后值、差异集（含稳定 `key`/`sig`）。是批注与汇总的唯一数据源，可反查任一差异 ↔ CERT 表/行/字段 ↔ DRAFT 表/行/字段。 |
| `批注版报告草稿.docx` | 差异批注写回 DRAFT 后的报告草稿；批注含差异字段、CERT 值、DRAFT 值、差异类型。 |
| `差异汇总.docx` | 独立差异汇总，1、2、3… 连续编号；批注锚点失败的差异也在此保留并标注。 |

说明：
- 该示例跑的是 `rules.version=strict-v1`（逐字比较）。项目默认规则是 `rules/normalization.json`（`normalized-v2`，启用一组无意义差异归一化），两者差异集会不同，属正常。
- `verification.json` 里的 `cert_path`/`draft_path` 是生成当时的绝对路径（旧样本目录）；样本内容与 `samples/data/` 一致，仅路径不同。
- 这些是脱敏样本的核对产物，仅供演示与回归，请勿外传。
