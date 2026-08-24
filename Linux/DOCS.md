# 文档路由 — CertAgent

> 🤖 首次进入本项目，按需加载以下文档。

## 顶层文档
| 文档 | 作用 | 何时读 |
|---|---|---|
| `BLUEPRINT.md` | 项目身份 / 核心原则 / 顶层规划 / 决策偏好 | 最先读，决策以此为准 |
| `README.md` | 架构 / 安装 / 运行命令 | 上手运行 |
| `记忆库说明.md` | 长期记忆存储位置、格式、管理者整理方法 | 管理/优化规则时 |

## 目录结构
```
CertAgent/
├── BLUEPRINT.md            # 项目蓝图（最高级文档）
├── DOCS.md                 # 本文件：文档路由
├── README.md               # 架构 + 安装 + 运行
├── 记忆库说明.md            # 记忆库存储与整理说明
├── cli.py                  # CLI 入口
├── check_stats.py          # 管理者一键查看使用统计
├── requirements.txt / .env.example
├── compare_core/           # 核心引擎（独立可跑，不依赖 LangGraph）
│   ├── config.py           # 运行配置（Pydantic + 环境变量）
│   ├── models.py           # 数据模型（Row/DiffItem/Suggestion/MemoryHint...）
│   ├── parser/             # 文档解析（doc→docx 转换 + 表格解析）
│   ├── differ/             # 归一化 + 对齐 + 差异分类 + 决策解析 + 审计
│   ├── rules/              # 正向规则 + 反向规则（YAML）
│   ├── suggester/          # 建议：规则动作 + LLM/mock 归纳
│   ├── writer/             # 生成整合清单 + 对照表 docx
│   ├── memory/             # 长期记忆：决策落盘 + 指纹聚合读回
│   ├── nodes.py / pipeline.py  # 节点函数 + 编排（CLI/图共用）
│   └── trace.py            # 运行追踪
├── graph/                  # LangGraph 编排层（可选，人在环 interrupt）
├── webapi/                 # Web 服务（FastAPI）
│   ├── app.py              # 路由装配
│   ├── auth.py             # JWT 认证
│   ├── jobs.py / runner.py # 任务管理 + 执行器
│   ├── analytics.py        # 后台使用统计（中间件 + 查询）
│   ├── schemas.py / settings.py
├── frontend/               # Vite + React 前端
│   └── src/pages/          # LoginPage / WorkspacePage / ReviewPage(确认页)
├── tests/                  # 冒烟/单测/实验脚本
└── fixtures/               # 测试样例（orig.json / plm.json）
```

## 运行时数据（不在仓库，自动生成于 runs/）
- `runs/feedback.jsonl` — 长期记忆（人工决策+理由）
- `runs/analytics.jsonl` — 使用统计埋点
- `runs/*/` — 各次运行的整合清单 / 对照表 / trace

## 常用命令
```bash
# CLI（mock，无需 LLM/Word，用 fixture）
python cli.py --orig-json fixtures/orig.json --plm-json fixtures/plm.json --out runs/out

# 启动后端
python -m webapi        # http://localhost:8000

# 启动前端（开发）
cd frontend && npm run dev   # http://localhost:3000

# 管理者查看使用统计
python check_stats.py
```
