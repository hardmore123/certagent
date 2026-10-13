# 输出示例

项目二的输出产物：批注版 DRAFT + 编号差异汇总。

## 子目录
- `samples_expected_outputs/`：主代码 `samples/expected_outputs/` 自带输出样例
  - `批注版报告草稿.docx`（差异批注写在 DRAFT 原位）
  - `差异汇总.docx`（1、2、3… 连续编号，含 CERT 值/DRAFT 值/差异类型/位置）
  - `verification.json`（完整 VerifyResult）
- `真实运行产物_acceptance_2026-08-28/`：真实验收运行产物（来自主代码 `runs/acceptance_2026-08-28/`，同上三件产物）

## 产物说明
- **批注版报告草稿.docx**：在 DRAFT 原位以 Word 批注标注每处差异（锚点失败降级到汇总）
- **差异汇总.docx**：按 1、2、3 顺序列出全部差异项，供审批人确认
- **verification.json**：完整核对结果（cert/draft blocks + diffs + row_diffs + warnings）

> 注：CLI/Web 运行时产物落在 `runs/`（已从交接包排除）；如需查看更多历史运行产物，见原仓库 `报告草稿准确性核对/runs/`。
