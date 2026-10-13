# 需求与设计文档

项目二的需求、设计、任务分解、LLM 门禁等文档。

## 文件清单
- `交接文档.md`：**项目二最详尽交接说明**（314 行，功能/架构/目录/流程/规则/LLM/已实现/未实现/API/排错）
- `design.md`：设计摘要（架构/数据模型/正确性属性/错误处理/测试策略）
- `tasks.md`：P0–P7 任务分解与状态（已实现/BLOCKED/未实现）
- `LLM_RELEASE_GATE.md`：LLM 发布门禁清单与回滚步骤
- `交付清单.md`：交付物清单
- `报告草稿准确性核对_可行性方案.md`：可行性方案
- `两个项目导读.md`：项目一与项目二的边界导读
- `大模型接口说明.md`：LLM 网关/鉴权/协议/参数/错误码/脱敏（密钥占位）

## 完整 spec
两套完整 spec 副本在 `主代码/docs/specs/`（随主代码带走）：
- `report-draft-verify/`：确定性核对设计基线
- `report-draft-llm-integration/`：LLM 集成 requirements/design/tasks

## 阅读建议
1. 先读 `两个项目导读.md` 明确项目边界
2. 再读 `交接文档.md`（最全面）
3. `design.md` 看设计摘要，`tasks.md` 看任务状态
4. LLM 相关看 `LLM_RELEASE_GATE.md` + `大模型接口说明.md`
