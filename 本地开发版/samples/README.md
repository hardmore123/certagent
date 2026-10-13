# 样本说明（项目一 · 清单整合）

本目录把分散在工作区的真实脱敏样例归集到项目内，让交接方无需外部依赖即可试跑并理解输入输出。

> 均为受控脱敏数据，仅供本项目演示与回归，请勿外传。

## inputs/ 输入样例

### 75U66Q/（海信机型，一整套）
| 文件 | 角色 |
|---|---|
| `原报告清单-输入.doc` | A = 原始/旧版本清单（整合输入之一） |
| `PLM导出清单-输入.doc` | B = PLM 新品/新版本清单（整合输入之二） |
| `关键件清单-输出参照.doc` | 人工整合后的关键件清单（期望输出参照） |
| `变更前后对照表-输出参照.doc` | 人工做的变更前后对照表（期望输出参照） |

这是最适合理解"A+B → 整合清单 + 对照表"的一组：前两份是输入，后两份是人工期望输出，可用来对比程序产物。

### 东芝85ZXSF/（另一机型，已解密）
| 文件 | 角色 |
|---|---|
| `PLM导出清单-新品.docx` | B 新品清单 |
| `原始清单-人工已整理.docx` | A 原始清单 |
| `输出-合成后清单.doc` | 整合后清单（输出参照） |
| `输出-合成后变更前后对照表.doc` | 整合后对照表（输出参照） |

### fixtures/（在项目根，不在本目录）
`../fixtures/orig.json`、`../fixtures/plm.json` 是解析后的结构化 JSON，用于**无需 Word/LLM** 的冒烟测试。

## expected_outputs/ 输出示例

来自 `runs/e2e_groups_llm_2026-07-28/`（真实端到端运行，LLM + 分组）：

| 文件 | 说明 |
|---|---|
| `整合版关键件清单.docx` | 整合产物（词级红字 + 黄色高亮差异） |
| `变更前后对照表.docx` | 变更前后对照表 |
| `result.json` | 结构化结果（差异分类、匹配、决策） |
| `run.log` | 运行日志 |

## 怎么用这些样本跑

```bash
# 结构化 JSON 冒烟（无需 Word/LLM）
python cli.py --orig-json fixtures/orig.json --plm-json fixtures/plm.json --out runs/out

# 真实 .doc + 真 LLM（需 Word/LibreOffice + .env 配好 LLM_*）
python cli.py --orig "samples/inputs/75U66Q/原报告清单-输入.doc" --plm "samples/inputs/75U66Q/PLM导出清单-输入.doc" --out runs/out --mode llm
```

> 注意：这些是**项目一（清单整合）**的样例。项目二（报告草稿核对）的样例是 100E7S + A2026 那一对，在 `../报告草稿准确性核对/samples/`，别混用。
