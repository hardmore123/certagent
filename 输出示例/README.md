# 输出示例

项目一的输出产物。

## 子目录
- `samples_expected_outputs/`：代码仓库自带的完整输出样例（来自 `list-merge-demo/samples/expected_outputs/`）
  - `整合版关键件清单.docx`（合并后的完整清单）
  - `变更前后对照表.docx`（逐项差异对照，含批注/高亮）
  - `result.json` + `run.log`（运行结果与日志）
- `真实运行产物_result目录/`：真实运行生成的产物（来自工作区 `result_*` 目录）
  - `result_2026-07-23/`、`result_东芝85ZXSF_2026-07-24/`、`result_东芝85ZXSF_2026-07-27/`
  - 每个目录含 `整合版关键件清单.docx` + `变更前后对照表.docx`

## 产物说明
- **整合版关键件清单.docx**：合并后的完整关键件清单
- **变更前后对照表.docx**：逐项差异对照，含批注/高亮，供人工审阅

> 注：CLI/Web 运行时产物默认落在 `runs/`（已从交接包排除）；如需查看大量历史运行产物，见原仓库 `list-merge-demo/runs/`。
