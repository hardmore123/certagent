# Parser Test 0727

用于比较认证关键件清单的三种解析路线：

1. Word COM + pywin32：当前生产候选基线，直接解析 `.doc`；
2. `.doc → .docx → python-docx`：转换和解析解耦，比较转换后结构是否保持；
3. Word → PDF/图片 → MinerU / Marker / Qwen-VL：视觉/版面路线，当前先完成渲染和环境预检，模型调用需显式配置。

## 运行

在 Windows、已安装 Microsoft Word 的环境中运行：

```text
python "c:/Users/likunyuan/Desktop/项目/parser test0727/run_benchmark.py"
```

可选参数：

```text
--methods com,docx,visual
--cases u66q,toshiba
--enable-remote-vision
```

## 统一评测指标

- 成功/失败和耗时；
- 总行数、表1/表2行数；
- 关键字段填充率；
- 分组标题数量；
- 有型号无名称；
- 规格材料与制造商相同的列错位征兆；
- python-docx 结果与 COM 基线的字段多重集差异；
- PDF页数、渲染图片数量；
- MinerU/Marker/Qwen-VL 是否可用及失败原因。

## 重要说明

- python-docx 不能直接读取老式二进制 `.doc`，因此第二路线的转换仍需要 Word COM；比较的是“解析阶段”而不是“转换阶段”。
- MinerU、Marker 更偏 PDF 版面/文档解析管线，Qwen-VL 才是视觉大模型判断路线，三者应分别记录结果，不能混成一个准确率。
- 当前不把视觉路线的预检结果当成解析准确率；没有模型、命令或接口配置时会明确记录 `blocked_missing_config`。
- 原始输入不会被覆盖，所有中间 `.docx`、PDF、图片、JSON 和报告写入 `results/`。

## 已实现文件

- `manifest.json`：固定两组真实样例及预期数据行基线；
- `parsers/docx_route.py`：Word COM 转换 `.docx`，再使用 `python-docx` 读取表格、分组和合并单元格；
- `parsers/visual_route.py`：本地 Word 转 PDF、PyMuPDF 渲染页面，并检查 MinerU/Marker/Qwen-VL 配置；
- `run_benchmark.py`：统一计时、字段填充率、异常指标、JSON 结果、CSV/Markdown 汇总和 COM 字段多重集对比；
- `results/`：每次运行使用 `run_YYYY-MM-DD_HHMMSS/` 独立目录，不覆盖历史结果。

## 已验证结果

75U66Q 的 `.docx/python-docx` 路线已在两份真实输入上解析出 `475` 行，其中表1 `438` 行、表2 `37` 行，分组事件 `11` 个。修正转换后合并列的相邻表头对齐后，表1关键字段填充率为：名称、型号、制造商、生产企业、认证标准、证书号均 `100%`，规格材料 `406/438 (92.69%)`。与既有 COM 基线按重复行字段指纹比较时，当前样例初步为 `403/475 (84.84%)`；该值是“转换后字段与 COM 的严格指纹一致率”，不是业务准确率，差异需要继续分类为 Word 转换结构差异、字段内容差异或解析缺陷。

视觉路线目前只允许本地处理，不会自动向外部 API 上传文档或图片。未设置 `MINERU_CMD`、`MARKER_CMD` 或 `QWEN_VL_API_BASE + QWEN_VL_MODEL` 时，状态必须是 `blocked_missing_config`；即使完成 PDF 和页面图片渲染，也不能纳入解析准确率。若 Word PDF 导出失败，结果记录为 `failed`，需要结合 Word 版本、PDF 导出权限和临时文件状态排查。

## 还需要确认的信息

1. 本机 Microsoft Word 的版本、位数，以及是否允许后台 Word COM 转换/导出 PDF；
2. 是否允许安装 LibreOffice 作为第二路线的非 Word 转换备选；
3. MinerU、Marker 是否允许本地安装，具体版本、命令或 Python 包入口；
4. Qwen-VL 是本地模型还是内网 API；若为 API，需要授权后的地址、模型名、鉴权方式和 JSON 输出 schema；
5. 是否允许把认证文档/页面图片发送到该已授权视觉接口；默认不发送；
6. 视觉路线期望输出的是逐行表格 JSON、版面 Markdown，还是同时输出字段置信度和页面/坐标引用；
7. 是否有人工确认后的标准 JSON/Excel 作为 parser 的金标准。当前 `manifest.json` 中的行数只是结构基线，不能替代字段级金标准。
