# 样本说明（samples/）

本目录提供可复现的核对样本与结构基线，供交接方按文档一键跑通并理解核对口径。

## 目录结构

| 路径 | 说明 |
|---|---|
| `manifest.json` | 样本清单：CERT/DRAFT 的角色、路径、各目标子块所在表索引、总表数（2026-09-01 结构基线） |
| `gold_baseline.json` | 结构基线（机器推断，非业务金标准）：期望的表数与各类子块数量、待补的验收指标 |
| `data/` | 实际样本文件（见下） |
| `data/_converted/` | DRAFT 的 .docx 转换件 + 转换脚本 `_com_convert.py` |

## 样本角色

| 角色 | 文件名前缀 | 文件 | 说明 |
|---|---|---|---|
| CERT 认证资料（应然基准，超集） | `A20` | `data/A2026CCC0808-...-P 安全描述+EMC（1.26） (2).docx` | 29 张表，含安全/EMC 清单、变更确认表、产品描述、图片、声明页 |
| DRAFT 报告草稿（实然对象，批注对象） | `100` | `data/_converted/100E7S-PRO(01)_安全&EMC关键件清单 (1).docx` | 2 张表（安全清单、EMC 清单） |

文件名规则：`A20` 开头是 CERT，`100` 开头是 DRAFT（大小写不敏感），由 `manifest.json.filename_role_rules` 定义。

## .doc → .docx 转换

原始 DRAFT 为 `.doc`（`data/100E7S-PRO(01)_...(1).doc`）。核对引擎优先吃 `.docx`，`.doc` 由 `report_verify/converter.py` 在运行时经 Word COM / LibreOffice 转换。离线复现转换可用 `data/_converted/_com_convert.py`（Windows + Word COM）。本目录已提供转换好的 `.docx`，可直接使用。

## 跑通样本

在项目根目录：

```powershell
uvicorn webapi.app:app --host 0.0.0.0 --port 8010
# 浏览器打开 http://127.0.0.1:8010/ ，CERT 传 data 下 A20 文件，DRAFT 传 _converted 下 docx
```

或用 CLI：

```powershell
python cli.py --cert "samples\data\A2026CCC0808-4944044（00501-CG2026-0353）-P 安全描述+EMC（1.26） (2).docx" --draft "samples\data\_converted\100E7S-PRO(01)_安全&EMC关键件清单 (1).docx" --out runs\sample_run
```

## 当前样本的核对事实（来自 manifest / baseline）

- CERT 共 29 张表：识别出 safety_list（表 7、20）、emc_list（表 28）、change_confirmation（表 4）、product_description（表 5）；其余 24 张表进入 unrecognized 元数据（图片/声明页/其他报告表，不参与字段核对但不静默丢弃）。
- DRAFT 共 2 张表：safety_list（表 1）、emc_list（表 2）。
- DRAFT 缺少变更确认表与产品描述子块，这两类差异只进入差异汇总，不伪造 DRAFT 批注锚点。

## 重要说明（脱敏与合规）

- `gold_baseline.json` 是机器推断的**结构基线**，不是业务字段金标准。四类子块仍需业务人员逐字段标注一致/不一致后，才能升级为 `field_gold_v1` 并据此计算定位召回、字段差异召回、误报率、批注定位成功率。
- 这些样本为受控脱敏数据，仅供本项目核对能力演示与回归，请勿外传或用于非授权用途。
- CERT 文件约 141MB（含内嵌对象），体积较大；若仓库不便承载大文件，可改为 Git LFS 或由交接方从受控数据目录单独获取（届时把 `samples/data/` 从仓库移除并在 `manifest.json` 改回受控路径即可）。
