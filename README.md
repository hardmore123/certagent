# CertAgent — 认证清单整合系统

两份 Word 关键件清单（原始清单/旧版本 与 PLM新品/新版本）→ 判断差异 → AI 建议 → 人工确认（接受/拒绝/手动匹配纠正）→ 生成【整合清单】+【变更前后对照表】，并记录决策沉淀进长期记忆用于持续优化。

> 顶层文档见 `BLUEPRINT.md`（项目原则）与 `DOCS.md`（文档路由 + 目录结构）。

## 架构（分层，依赖单向）
```
CLI(cli.py) / Web(webapi) → 编排层 graph/(LangGraph,可选) → 核心引擎 compare_core/(独立可单跑)
                                                             解析→判断(diff)→建议(规则+LLM)→修改(写Word)→记忆
```
- **核心引擎 compare_core/** 不依赖 LangGraph，可 CLI 直接跑（默认）。
- **graph/** 用 LangGraph + `interrupt` 实现人在环（`--engine graph`）。
- **webapi/** FastAPI Web 服务，前端确认页人工决策。

---

## 环境要求

| 项 | 版本/要求 | 说明 |
|---|---|---|
| 操作系统 | Windows / Linux | Word COM 解析仅 Windows；Linux 用 LibreOffice 转换 |
| Python | **>= 3.11** | 后端 |
| Node.js | **>= 18**（建议 20+） | 仅前端开发/构建需要 |
| Word 或 LibreOffice | 任一 | .doc → .docx 转换；纯 .docx/JSON 输入可不装 |
| LLM 接口 | 可选 | 聚好看 higpt 网关或任意 OpenAI 兼容接口；不配则回退 mock |

---

## 依赖与版本

### 后端 Python（`requirements.txt`）
| 依赖 | 版本 | 用途 |
|---|---|---|
| pydantic | >=2 | 数据模型 / 配置 |
| pyyaml | >=6 | 规则文件（YAML）解析 |
| python-docx | >=1.1 | 读写 Word（含原生批注） |
| requests | >=2.31 | 调用 LLM 接口（流式） |
| opencc-python-reimplemented | >=0.1.7 | 繁→简归一化 |
| pywin32 | >=306（仅 Windows） | Word COM 解析/转换 |
| langgraph | >=0.2（可选） | 人在环编排（`--engine graph`） |
| fastapi | >=0.110（Web） | Web 服务 |
| uvicorn[standard] | >=0.29（Web） | ASGI 服务器 |
| python-multipart | >=0.0.9（Web） | 文件上传 |
| pyjwt | >=2.8（Web） | 登录 JWT |

> 仅跑 CLI/核心引擎：装前 6 项即可。要 Web 服务：再装后 4 项（fastapi/uvicorn/python-multipart/pyjwt）。

### 前端（`frontend/package.json`）
| 依赖 | 版本 |
|---|---|
| react / react-dom | ^19.2 |
| vite | ^8.1 |
| typescript | ~6.0 |
| @vitejs/plugin-react | ^6.0 |
| oxlint | ^1.71 |

---

## 安装

### 后端
```bash
pip install -r requirements.txt
cp .env.example .env        # 用 llm 模式时填写 LLM_*（聚好看网关需 LLM_USER_KEY）
```

### 前端
```bash
cd frontend
npm install
```

---

## 快速启动

### 场景 1：CLI 单机跑（最快验证）

```bash
# 1. 安装后端依赖
pip install -r requirements.txt

# 2. 配置（用 mock 模式可跳过，不需要 LLM）
cp .env.example .env

# 3. 用 fixture 冒烟（无需 Word/LLM）
python cli.py --orig-json fixtures/orig.json --plm-json fixtures/plm.json --out runs/out
# 产出：runs/out/整合版关键件清单.docx + 变更前后对照表.docx

# 4. 用真实 .doc 文件 + 真 LLM（需 Word/LibreOffice + .env 配好 LLM_*）
python cli.py --orig "原报告清单.doc" --plm "PLM导出清单.doc" --out runs/out --mode llm
```

### 场景 2：Web 服务（前后端完整，供多人使用）

```bash
# 1. 安装后端依赖
pip install -r requirements.txt

# 2. 配置
cp .env.example .env   # 至少填 LLM_*（或 SUGGESTER_MODE=mock 跳过 LLM）

# 3. 安装前端依赖
cd frontend
npm install
cd ..

# 4. 启动后端（监听 0.0.0.0:8000，带热重载）
python -m webapi
# 看到 "Uvicorn running on http://0.0.0.0:8000" 即成功

# 5. 启动前端（另开一个终端）
cd frontend
npm run dev
# 看到 "Local: http://localhost:3000/" 即成功

# 6. 浏览器访问
#    http://localhost:3000    ← 前端页面（开发模式，自动代理 /api/* 到后端 8000）
#    默认账号：admin / admin
```

### 场景 3：仅后端 API（无前端，配合 curl/Postman 或自动化脚本）

```bash
pip install -r requirements.txt
cp .env.example .env
python -m webapi
# http://localhost:8000/docs    ← FastAPI 自动生成的 Swagger UI 接口文档
```

---

## 使用流程（Web）

```
1. 登录（admin/admin）
2. 工作台 → "新建任务"上传两份清单（A=原始清单/旧版本, B=PLM新品/新版本）
3. 等待解析+比对完成（进度条）
4. 进入"差异确认"页 → 并排对照 A|B 视图
5. 逐行决策：接受 / 拒绝(丢弃) / 拒绝并匹配(选另一侧对应行) / 其实相同 / 拆两独有
6. 提交决策 → 系统生成：
   - 整合版关键件清单.docx
   - 变更前后对照表.docx
7. 下载产物 / 查看审计报告
```

---

## 停止服务

```bash
# 后端（Ctrl+C 即可；或找进程杀）
# 前端（Ctrl+C）
```

---

## 其它命令

```bash
# 管理者查看使用统计（自动登录+打印汇总）
python check_stats.py

# LangGraph 人在环编排（CLI 交互式确认）
python cli.py --orig-json fixtures/orig.json --plm-json fixtures/plm.json --engine graph
```

---

## 配置（`.env`）

```bash
# LLM 接口（聚好看 higpt 网关；不配则回退 mock）
LLM_BASE_URL=https://inner-apisix.hisense.com/higpt-new/v1
LLM_API_KEY=你的key
LLM_USER_KEY=你的user_key        # 聚好看网关需要；公网 OpenAI 兼容接口留空
LLM_MODEL=deepseek-v4-flash
SUGGESTER_MODE=llm               # llm | mock

# 长期记忆 / 统计（默认落在 runs/）
MEMORY_ENABLED=true
# FEEDBACK_FILE=runs/feedback.jsonl
```
> `.env` 含密钥，不要提交 git（应在 `.gitignore` 中）。

---

## 目录
- `compare_core/parser` 文档解析（Word COM / LibreOffice / python-docx，容错重心）
- `compare_core/differ` 归一化 + 匹配键对齐 + 差异分类 + 置信度 + 决策解析(resolve) + 审计（纯代码）
- `compare_core/rules` 正向规则 + 反向规则（误报防护，YAML）
- `compare_core/suggester` 建议：规则化动作 + LLM/mock 变更项归纳
- `compare_core/writer` 生成整合清单 + 对照表 docx（批注/高亮）
- `compare_core/memory` 决策落盘 + 指纹聚合读回 + 反哺建议（详见 `记忆库说明.md`）
- `graph/` LangGraph 编排层
- `webapi/` FastAPI Web 服务（含 `analytics.py` 使用统计）
- `frontend/` Vite + React 前端（确认页 ReviewPage）

## 数据保存（全文件系统，无数据库）
| 数据 | 格式 | 位置 |
|---|---|---|
| 正向/反向规则 | YAML | `compare_core/rules/data/` |
| 长期记忆（决策+理由） | JSONL | `runs/feedback.jsonl` |
| 使用统计 | JSONL | `runs/analytics.jsonl` |
| 运行产物 | docx/JSON | `runs/*/` |
