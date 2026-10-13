# 需求文档：认证清单三路线解析对比测试

## Introduction

本规格定义一个仅用于本地测试和结果留存的认证清单解析对比基准。测试对象为两组真实 `.doc` 清单，比较 Word COM 基线、`.doc → .docx → python-docx` 转换解析路线，以及 Marker 2.0.0 本地 PDF 解析路线；同时单独验证 PDF 导出、页面渲染和图片产物。规格只定义测试行为、统一结果和验收口径，不定义实现代码。

## Glossary

- **Benchmark_System（基准测试系统）**：执行输入隔离、路线运行、计时、指标计算、结果保存和汇总的本地测试系统。
- **COM_Baseline（Word COM 基线）**：使用本机 Microsoft Word 2016 版本 `16.0.4266.1001`、32 位 Word COM 直接读取 `.doc` 并产生统一行结果的第一条路线。
- **Docx_Route（DOCX 转换解析路线）**：使用 Word COM 将 `.doc` 转换为 `.docx`，再使用 `python-docx` 读取表格并产生统一行结果的第二条路线；允许记录 LibreOffice 作为另行配置的转换备选，但备选结果不得冒充 COM_Baseline。
- **Marker_Route（Marker 本地 PDF 路线）**：使用本地 `marker-pdf 2.0.0` 从 PDF 生成 Markdown 和/或 JSON，并尝试将结果映射为统一行的第三条路线。
- **Pdf_Render_Route（PDF 页面渲染路线）**：将清单导出为 PDF，逐页渲染为图片并记录页面、图片和产物信息的测试路线；页面渲染完成不等于结构化解析成功。
- **Route（测试路线）**：COM_Baseline、Docx_Route、Marker_Route 或 Pdf_Render_Route 中的一条可独立记录的处理路径。
- **Test_Case（测试样例）**：manifest 中登记的一份来源文件及其预期行数信息。
- **Run（测试运行）**：一次具有唯一运行标识和独立输出目录的完整或部分基准执行。
- **Unified_Row（统一 Row）**：所有可结构化路线使用的标准行对象，包含 `table`、`group`、`序号`、`位号`、`关键件名称`、`型号`、`规格材料`、`制造商`、`生产企业`、`认证标准`、`证书号`、`本次使用`、`备注`、`source`、`row_index` 和 `raw` 字段。
- **Table_1（表1）**：关键件主清单数据表；**Table_2（表2）**：备选件或电源单元清单数据表。
- **Group（分组）**：清单中的分组标题及其后续数据行所继承的分组上下文。
- **Field_Fill_Rate（字段填充率）**：指定表和字段中非空 Unified_Row 值的行数除以该表总数据行数所得的百分比；分母为零时记录为 `0%`。
- **Anomaly_Metric（异常指标）**：用于暴露解析风险的可计数指标，至少包括“有型号无关键件名称”和“规格材料与制造商相同”。
- **COM_Multiset_Comparison（COM 多重集对比）**：以 COM_Baseline 行指纹为基准，按重复次数比较候选路线行集合的匹配、缺失和额外数量；重复行不得被集合去重。
- **Artifact（中间产物）**：测试过程中保存的转换文件、PDF、页面图片、Markdown、JSON、统一行 JSON、日志和汇总报告。
- **Marker_Status（Marker 状态）**：Marker_Route 的受控状态，至少包括 `success`、`failed`、`blocked_missing_config` 和 `blocked_parser_invocation`。
- **Qwen_Vision_API（Qwen 视觉 API）**：可选的外部或内网视觉服务；本规格不把该服务作为必需路线，且当前地址、鉴权、图片权限和输出 Schema 尚未提供。
- **Unauthorized_External_Send（未经授权的外发）**：未得到明确接口地址、鉴权信息和文档/图片发送许可时，将源文档或页面图片发送到任何外部 API 的行为。
- **Temporary_Lock_File（临时锁文件）**：文件名以 `~$` 开头或由 Word 生成的编辑锁文件；此类文件不属于测试输入。
- **Status（执行状态）**：路线结果状态。成功、执行失败、缺少配置、缺少解析入口等状态必须与指标数值分开记录。

## 已知环境、输入和约束

1. 测试环境为 Windows；本机 Microsoft Word 为 2016，版本 `16.0.4266.1001`，32 位；允许后台 Word COM 批量转换和 PDF 导出。
2. 允许安装 LibreOffice，允许本地安装 MinerU/Marker；Marker 使用 `marker-pdf 2.0.0`，源码或虚拟环境位于 `C:\Users\likunyuan\Desktop\marker-master`。
3. Marker 推荐在 GT 730 上使用 CPU fast 模式。已知命令为 `.venv\\Scripts\\marker_single.exe input.pdf --output_dir output --mode fast`；也允许记录 `marker.scripts.convert` 或 `convert_single` Python 模块入口。实际采用的入口、版本和参数必须写入结果。
4. Qwen_Vision_API 尚未提供完整地址、鉴权方式、模型名、图片权限和输出 Schema；当前规格只将视觉 API 作为可选能力。未完成授权配置时，测试不得调用该 API，也不得用伪造内容填充 Unified_Row。
5. 已知真实样例基线如下：
   - 75U66Q 原报告清单：总计 475 行，Table_1 为 438 行，Table_2 为 37 行。
   - 75U66Q PLM 清单：总计 475 行，Table_1 为 438 行，Table_2 为 37 行。
   - 东芝原始清单：总计 159 行，Table_1 为 152 行，Table_2 为 7 行。
   - 东芝 PLM 清单：总计 175 行，Table_1 为 169 行，Table_2 为 6 行。
6. 当前已有 COM 字段多重集对比参考结果：75U66Q 某已验证路线为 `403/475 (84.84%)` 严格指纹一致率。该数值只表示路线字段指纹一致性，不得表述为业务准确率。

## Requirements

### Requirement 1: 测试输入登记与隔离

**User Story:** 作为测试人员，我希望每个样例和来源文件都被独立登记和隔离，以便重复运行不会覆盖原始资料或互相污染。

#### Acceptance Criteria

1. THE Benchmark_System SHALL 为每个 Run 分配唯一运行标识，并为每个 Test_Case、来源文件和 Route 建立独立输出范围。
2. WHEN Benchmark_System 发现 Temporary_Lock_File 时，THE Benchmark_System SHALL 跳过该文件并在 Run 日志中记录跳过原因。
3. THE Benchmark_System SHALL 以只读方式使用来源 `.doc` 文件，并将所有可写产物保存到 Run 的独立输出范围。
4. IF 来源文件不存在、路径不可读或文件类型不受支持，THEN THE Benchmark_System SHALL 将对应 Route 标记为 `failed` 并记录可定位的错误信息。
5. THE Benchmark_System SHALL 登记四个已知 Test_Case 文件的来源路径、文件标识和预期总行数、Table_1 行数、Table_2 行数。

### Requirement 2: COM 基线路线

**User Story:** 作为测试人员，我希望有一条直接读取 `.doc` 的 Word COM 基线，以便为其他结构化路线提供可复现参照。

#### Acceptance Criteria

1. WHEN COM_Baseline 处理受支持的 `.doc` 输入时，THE Benchmark_System SHALL 使用已登记的 Word 2016 环境信息记录版本 `16.0.4266.1001` 和 32 位架构。
2. WHEN COM_Baseline 完成解析时，THE Benchmark_System SHALL 将每一条数据行转换为 Unified_Row，并保留 Table_1、Table_2、Group 和源行位置。
3. WHEN COM_Baseline 处理 75U66Q 两份清单时，THE Benchmark_System SHALL 分别记录总计 475 行、Table_1 为 438 行和 Table_2 为 37 行的实际结果或明确差异。
4. WHEN COM_Baseline 处理东芝两份清单时，THE Benchmark_System SHALL 分别记录原始清单 159 行（152/7）和 PLM 清单 175 行（169/6）的实际结果或明确差异。
5. IF Word COM 转换、读取或退出发生异常，THEN THE Benchmark_System SHALL 记录 `failed`、异常阶段、错误信息和已生成的 Artifact，并保留其他 Route 的执行机会。

### Requirement 3: DOC 转 DOCX 再由 python-docx 解析

**User Story:** 作为测试人员，我希望分离转换阶段和解析阶段，以便判断差异来自 `.doc` 转换还是 `python-docx` 表格读取。

#### Acceptance Criteria

1. WHEN Docx_Route 处理 `.doc` 输入时，THE Benchmark_System SHALL 保存转换后的 `.docx` Artifact，并记录转换工具、版本、开始结束时间和转换状态。
2. WHEN Docx_Route 读取转换后的 `.docx` 时，THE Benchmark_System SHALL 使用 python-docx 解析表格、分组标题、横向合并和纵向合并信息，并输出 Unified_Row。
3. WHERE LibreOffice 被配置为转换备选工具，THE Benchmark_System SHALL 将 LibreOffice 结果作为独立转换变体记录，并与 Word COM 转换结果分开统计。
4. WHEN Docx_Route 产生 Unified_Row 时，THE Benchmark_System SHALL 记录转换 `.docx` 路径、解析阶段状态和转换前来源路径。
5. IF 转换成功但 python-docx 解析失败，THEN THE Benchmark_System SHALL 将 Route 标记为 `failed`，保留 `.docx` Artifact，并将失败阶段标记为解析阶段。
6. IF 转换失败，THEN THE Benchmark_System SHALL 将 Route 标记为 `failed`，记录转换失败原因，并不把空 Unified_Row 结果解释为解析成功。

### Requirement 4: PDF 导出和页面渲染

**User Story:** 作为测试人员，我希望单独验证 PDF 和页面图片产物，以便区分文档导出、页面渲染和结构化解析问题。

#### Acceptance Criteria

1. WHEN Pdf_Render_Route 处理可读的 Word 清单时，THE Benchmark_System SHALL 保存 PDF Artifact，并记录 PDF 导出工具、页数和导出耗时。
2. WHEN PDF 导出完成时，THE Benchmark_System SHALL 按页生成图片 Artifact，并记录 PDF 页数、实际图片数量、图片格式、渲染参数和渲染耗时。
3. WHEN 页面渲染完成时，THE Benchmark_System SHALL 将每张图片与来源文件、页码和 Run 标识关联保存。
4. IF PDF 导出失败，THEN THE Benchmark_System SHALL 将 PDF 导出状态标记为 `failed`，记录错误信息，并不伪造页数或图片数量。
5. IF 页面数量与图片数量不一致，THEN THE Benchmark_System SHALL 记录该异常并将 Pdf_Render_Route 标记为 `failed`。
6. THE Benchmark_System SHALL 将页面渲染成功状态与 Marker_Route 的结构化解析成功状态分开报告。

### Requirement 5: Marker 2.0.0 本地 PDF 到 Markdown/JSON

**User Story:** 作为测试人员，我希望在本地使用固定版本 Marker 处理 PDF，以便评估版面解析产物和结构化映射能力，而不依赖未经授权的外部服务。

#### Acceptance Criteria

1. WHEN Marker_Route 启动时，THE Benchmark_System SHALL 记录 `marker-pdf` 版本 `2.0.0`、本地路径 `C:\Users\likunyuan\Desktop\marker-master`、执行入口、命令参数和运行模式。
2. WHEN Marker_Route 具备本地解析入口和 PDF 输入时，THE Benchmark_System SHALL 使用配置的 `marker_single.exe` 或 `marker.scripts.convert/convert_single` 入口生成并保存 Markdown 和可用的 JSON Artifact。
3. WHERE GT 730 CPU fast 模式被配置时，THE Benchmark_System SHALL 记录 CPU fast 模式及其配置，而不将硬件模式混入字段准确率指标。
4. WHEN Marker 只生成 Markdown 或 JSON 不含可靠表格结构时，THE Benchmark_System SHALL 记录“生成成功但结构化映射失败”，并将结构化解析结果标记为失败或不可用。
5. WHEN Marker Markdown/JSON 能够可靠表达表格行时，THE Benchmark_System SHALL 按已验证的字段映射规则将结果映射为 Unified_Row，并保存原始 Markdown/JSON 与映射结果。
6. IF Marker 配置缺失，THEN THE Benchmark_System SHALL 使用 `blocked_missing_config`，记录缺失项，并不生成伪造的 Markdown、JSON 或 Unified_Row。
7. IF Marker 入口不可调用、命令不存在或入口返回不可解析结果，THEN THE Benchmark_System SHALL 使用 `blocked_parser_invocation` 或 `failed`，记录入口诊断和已有 Artifact。
8. THE Benchmark_System SHALL 将 Marker Markdown/JSON 到 Unified_Row 的字段映射作为待验证需求单独记录，且不得因 Markdown 文件存在就判定 Marker_Route 解析成功。

### Requirement 6: Unified_Row 字段和映射完整性

**User Story:** 作为评测人员，我希望所有可比较路线使用同一行结构，以便行数、填充率和字段多重集能够在路线之间对齐。

#### Acceptance Criteria

1. THE Benchmark_System SHALL 为每条结构化数据行提供 Unified_Row 的 `table`、`group`、`序号`、`位号`、`关键件名称`、`型号`、`规格材料`、`制造商`、`生产企业`、`认证标准`、`证书号`、`本次使用`、`备注`、`source`、`row_index` 和 `raw` 字段。
2. WHEN Route 输出缺少某个统一字段时，THE Benchmark_System SHALL 以空值记录该字段并保留原始行内容到 `raw`，而不是删除该行。
3. WHEN Route 识别分组标题或跨行合并数据时，THE Benchmark_System SHALL 将分组上下文和恢复后的字段值写入 Unified_Row，并记录源行位置。
4. WHEN Marker_Route 进行字段映射时，THE Benchmark_System SHALL 为每个映射字段记录映射来源或“未验证”标记。
5. IF Marker_Route 无法可靠映射结构化字段，THEN THE Benchmark_System SHALL 保留 Markdown/JSON 原文并将 Unified_Row 映射状态标记为失败，不得把原文文件存在作为字段填充成功。

### Requirement 7: 行数、字段填充率、分组和异常指标

**User Story:** 作为评测人员，我希望每条路线都输出一致的量化指标，以便比较结构保持能力和字段质量。

#### Acceptance Criteria

1. WHEN Route 完成或进入终止状态时，THE Benchmark_System SHALL 记录总数据行数、Table_1 行数和 Table_2 行数。
2. WHEN Route 产生 Unified_Row 时，THE Benchmark_System SHALL 按 Table_1 和 Table_2 分别计算统一字段的 Field_Fill_Rate，并记录填充数量、分母和百分比。
3. THE Benchmark_System SHALL 对每条 Route 记录 Group 数量、分组事件数量和空分组行数量。
4. THE Benchmark_System SHALL 对每条 Route 记录至少“有型号无关键件名称”和“规格材料与制造商相同”两个 Anomaly_Metric 的数量及涉及行位置。
5. THE Benchmark_System SHALL 对每条 Route 记录总耗时、各阶段耗时、状态和错误摘要。
6. IF Route 未产生可比较的 Unified_Row，THEN THE Benchmark_System SHALL 将行数和填充率标为不可用或零并同时保留终止状态，不得把不可用指标当作零准确率。

### Requirement 8: COM 多重集对比

**User Story:** 作为评测人员，我希望将其他结构化路线与 COM 基线按行指纹进行多重集比较，以便发现缺行、重复行和字段差异。

#### Acceptance Criteria

1. WHEN COM_Baseline 和候选结构化 Route 均成功产生 Unified_Row 时，THE Benchmark_System SHALL 计算 COM_Multiset_Comparison。
2. THE Benchmark_System SHALL 使用包含 `table`、`group`、`关键件名称`、`型号`、`规格材料`、`制造商`、`生产企业`、`认证标准`、`证书号`、`本次使用` 和 `备注` 的行指纹进行比较。
3. THE Benchmark_System SHALL 保留指纹重复次数，并分别记录基线行数、候选行数、匹配数、候选缺失数、候选额外数和基线匹配百分比。
4. WHEN 候选 Route 无法成功结构化或 COM_Baseline 失败时，THE Benchmark_System SHALL 记录多重集对比不可用及原因。
5. THE Benchmark_System SHALL 在汇总中明确说明 COM 指纹匹配率是结构差异指标而非业务准确率。

### Requirement 9: 状态、阻断原因和结果可解释性

**User Story:** 作为测试负责人，我希望失败、阻断和成功被明确区分，以便测试报告不会把环境缺失误判为解析结果。

#### Acceptance Criteria

1. THE Benchmark_System SHALL 为每个 Route 记录 `success`、`failed`、`blocked_missing_config` 或 `blocked_parser_invocation` 中适用的 Status。
2. WHEN Route 因缺少外部或本地配置无法执行时，THE Benchmark_System SHALL 记录缺失配置名称、检测时间和阻断状态。
3. WHEN Route 因工具调用失败而终止时，THE Benchmark_System SHALL 记录命令或入口、退出信息、失败阶段和错误摘要。
4. IF Marker_Route 仅完成 Markdown 生成但结构化映射失败，THEN THE Benchmark_System SHALL 同时记录产物生成状态和结构化映射失败状态。
5. THE Benchmark_System SHALL 在 CSV、JSON 和 Markdown 汇总中同时展示 Status、耗时、行数、填充率可用性和错误摘要。

### Requirement 10: 本地安全边界和可选视觉 API

**User Story:** 作为资料安全负责人，我希望测试默认只在本地处理认证文档，以便避免未经授权泄露源文件和页面图片。

#### Acceptance Criteria

1. THE Benchmark_System SHALL 默认在本地完成 Word、PDF、图片、Marker Markdown 和 JSON 处理，并保存本地处理证据。
2. IF Qwen_Vision_API 未同时配置授权地址、鉴权信息、模型名、图片发送权限和输出 Schema，THEN THE Benchmark_System SHALL 不发送源文档或页面图片，并记录 `blocked_missing_config`。
3. WHERE Qwen_Vision_API 已获得明确授权并完成完整配置，THE Benchmark_System SHALL 在运行结果中记录接口标识、授权配置引用、发送范围和返回状态，但不得把视觉 API 结果与 Marker_Route 结果混为一条路线。
4. IF 任一处理步骤尝试向未授权外部 API 发送文档或图片，THEN THE Benchmark_System SHALL 阻止该发送并记录 Unauthorized_External_Send 安全事件。
5. THE Benchmark_System SHALL 不以占位文本、示例值或模型臆测内容填充缺失的 Unified_Row 字段。

### Requirement 11: 统一输出结构和中间产物留存

**User Story:** 作为测试负责人，我希望每次运行都有可追溯的文件结构和原始产物，以便复核结论、重现失败和审计路线差异。

#### Acceptance Criteria

1. THE Benchmark_System SHALL 为每次 Run 保存 manifest 快照、环境信息、路线配置、状态日志和汇总报告。
2. WHEN 任一路线执行转换或解析时，THE Benchmark_System SHALL 保存对应的 `.docx`、PDF、页面图片、Markdown、JSON、Unified_Row JSON 和错误日志中实际生成的 Artifact。
3. THE Benchmark_System SHALL 让每个 Artifact 关联 Run 标识、Test_Case、来源文件标识、Route、阶段和生成时间。
4. WHEN Run 完成时，THE Benchmark_System SHALL 输出机器可读 JSON、CSV 汇总和人可读 Markdown 汇总。
5. IF Artifact 保存失败，THEN THE Benchmark_System SHALL 记录保存失败状态和路径，并将受影响 Route 标记为 `failed` 或产物不可用。
6. THE Benchmark_System SHALL 保留历史 Run 的独立目录，并使后续 Run 不覆盖既有 Artifact。

### Requirement 12: 三路线对比报告与验收结论

**User Story:** 作为测试负责人，我希望报告能直接比较三条解析路线的行数、字段质量、风险和耗时，以便决定后续采用或继续验证的路线。

#### Acceptance Criteria

1. WHEN Run 至少包含 COM_Baseline、Docx_Route 和 Marker_Route 结果时，THE Benchmark_System SHALL 按 Test_Case 和来源文件生成三路线对比表。
2. THE Benchmark_System SHALL 在对比表中展示每条 Route 的 Status、总耗时、总行数、Table_1/2 行数、字段填充率、Group 数量、Anomaly_Metric、PDF 页数、图片数量和 COM_Multiset_Comparison 可用性。
3. WHEN 某 Route 被阻断或结构化映射失败时，THE Benchmark_System SHALL 在对比表中展示阻断或失败原因，并将对应指标标记为不可用。
4. THE Benchmark_System SHALL 对 75U66Q 和东芝四份已知输入分别给出与已知基线的行数差异，而不把预期值直接覆盖为实际值。
5. THE Benchmark_System SHALL 在报告结论中分别说明 COM 基线、DOCX 转换解析、Marker 产物生成、Marker 结构化映射和 PDF 页面渲染的验证结论。
6. THE Benchmark_System SHALL 将“Marker Markdown/JSON 到 Unified_Row 的字段映射”列为待验证结论，直到存在可审查的映射证据和字段级结果。

## 待确认信息

以下信息不阻塞本需求文档创建，但在进入设计和执行前必须作为配置或测试前置条件补齐：

1. Qwen_Vision_API 的完整地址、鉴权方式、模型名、图片发送权限和 JSON 输出 Schema；未补齐时保持可选且阻断，不调用。
2. 是否实际启用 LibreOffice 转换备选，以及 LibreOffice 版本和命令入口。
3. Marker 本地虚拟环境的确切解释器、模型缓存位置、是否允许下载模型和最终采用的入口。
4. PDF 导出所需的 Word 权限、临时文件清理策略和输出 PDF 命名约定。
5. 是否提供字段级人工金标准；当前行数基线仅用于结构回归，不替代字段级准确性金标准。

## 非目标

- 本规格不实现认证清单合并、差异标红、业务变更归纳或 Word 写回。
- 本规格不把 Qwen_Vision_API 设为必需依赖，不在缺少授权时发送任何文档或图片。
- 本规格不把 PDF 页面渲染成功、Markdown 文件存在或 JSON 文件存在单独解释为结构化解析成功。
- 本规格不把 COM 多重集匹配率或字段填充率直接解释为业务准确率。
