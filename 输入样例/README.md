# 输入样例

项目一的输入是两份 Word 关键件清单：A=原始/旧版本、B=PLM 新品/新版本。

## 子目录
- `样例_75U66Q/`：75U66Q 机型的完整样例（输入 + 输出参照，来自工作区 `样例/`）
- `真实清单_东芝85ZXSF/`：东芝 85ZXSF 真实清单（输入 + 输出，来自工作区 `AI智能体-认证原始清单与新品清单合并/`，含 `.doc`/`.docx`/`.pdf` 多种格式与 `_converted/` 转换产物）
- `项目自带样例_samples_inputs/`：代码仓库自带样例输入（来自 `list-merge-demo/samples/inputs/`）
  - `75U66Q/`、`东芝85ZXSF/` 两个机型的输入与输出参照
- `README.md`：samples 目录的说明（来自 list-merge-demo/samples/README.md）

## 输入格式
支持 `.doc` / `.docx` / `.json`。`.doc` 会被自动转 `.docx`（Windows 用 Word COM，Linux 用 LibreOffice）。
