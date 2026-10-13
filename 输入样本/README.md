# 输入样本

项目二的输入是两份 Word 文档：CERT 认证资料（应然基准，A20 开头）+ DRAFT 报告草稿（实然对象，100 开头）。

## 子目录
- `真实样本_确认报告草稿/`：来自工作区 `确认报告草稿/`（DRAFT 关键件清单 100E7S-PRO）
- `样本副本_确认报告草稿样本/`：来自工作区 `确认报告草稿样本/`（DRAFT + `_converted/` 转换产物）
- `主代码自带_samples_data/`：主代码仓库 `samples/data/` 内置样本（DRAFT + `_converted/` 转换产物）

> **CERT 认证资料（141MB 超大文件）已移除**：原 `A2026CCC0808-4944044...安全描述+EMC（1.26）.docx`（140.86MB）因超过 GitHub/GitLab 单文件 100MB 限制已从交接包移除。该文件是 CERT 应然基准（A20 开头），如需可从原工作区 `项目/确认报告草稿/` 或 `项目/报告草稿准确性核对/samples/data/` 获取。DRAFT 关键件清单（100E7S-PRO，约1.5MB）完整保留在各子目录中。

## 顶层文件
- `README.md` / `manifest.json` / `gold_baseline.json`：主代码 samples 的说明、样本清单、结构基线（非业务金标准）

## 输入格式
支持 `.doc` / `.docx`。`.doc` 会由 `converter.py` 经 Word COM / LibreOffice 自动转 `.docx`。

> 注意：CERT 文件约 141MB（超大），上传需放开 multipart 上限（主代码 webapi 已处理，默认 500MB）。
