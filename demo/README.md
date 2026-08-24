# 变更-开发 清单整合 Demo

两份 Word 关键件清单 → 判断差异 → AI 建议 → 人工确认(是/否) → 生成【整合清单】+【变更前后对照表】，并记录决策用于后续优化。

## 架构（分层，依赖单向）
```
CLI(cli.py)  →  编排层 graph/ (LangGraph, 可选)  →  核心引擎 compare_core/ (独立可单跑)
                                                      解析→判断(diff)→建议(规则+LLM)→修改(写Word)→记忆
```
- **核心引擎 compare_core/** 不依赖 LangGraph，可 CLI 直接跑（`--engine core`，默认）。
- **graph/** 用 LangGraph + `interrupt` 实现人在环（`--engine graph`）。
- suggest 的对照表归纳支持 **真 LLM（限定 JSON 输出，强容错）** 与 **mock**（工程测试）。

## 安装
```
pip install -r requirements.txt
cp .env.example .env   # 用 llm 模式时填写 LLM_*
```

## 运行
```bash
# mock + 核心引擎（无需 LLM/Word 可用 fixture）
python cli.py --orig-json fixtures/orig.json --plm-json fixtures/plm.json --out runs/out

# 真实 doc + 真 LLM
python cli.py --orig 原报告清单.doc --plm PLM导出清单.doc --out runs/out --mode llm

# LangGraph 编排
python cli.py --orig-json fixtures/orig.json --plm-json fixtures/plm.json --engine graph
```

## 目录
- `compare_core/parser` 文档解析（Word COM，容错重心）
- `compare_core/differ` 归一化 + 匹配键对齐 + 差异分类 + 置信度（纯代码）
- `compare_core/rules` 正向规则 + 反向规则（误报防护）
- `compare_core/suggester` 建议：规则化动作 + LLM/mock 变更项归纳
- `compare_core/writer` 生成整合清单 + 对照表 docx
- `compare_core/memory` 决策落盘 + 相似检索（长期记忆雏形）
- `graph/` LangGraph 编排层

## 里程碑
M1 解析 · M2 diff · M3 编排出整合清单 · M4 人确认 · M5 LLM 对照表 · M6 记忆闭环
（详见 ../实现思路_变更清单整合Demo.md）
```
