# A/B 冻结清单（开发集）

**日期**: 2026-08-17  
**状态**: 已锁。修改须同步 ROADMAP，不得按开发集个例拧参。  
**范围**: LoCoMo 40 题分层开发集，**不是 holdout**。  
**最近一次开发集 A/B**: 2026-08-23，口径对齐后 40 题，结果 `logs/locomo_ab_dev.json`。static QA 37.5%，agentic QA 42.5%（+5pp），强制搜 4/40。这是诊断，不是发布结论。

## 锁死项

| 项 | 值 |
|---|---|
| 划分 | `stratified_sample`，类别 1–4，每类 10 题 |
| seed | `42` |
| 流式 | 关闭（正式臂只跑非流式） |
| Top-K | `5` |
| 主模型 / 端点 | `.env.local` 的 `LIGHTHERMES_MODEL` / `LIGHTHERMES_BASE_URL` |
| Embedding | `LIGHTHERMES_EMBEDDING_MODEL` + 独立缓存 |
| Trigger | `can_search ∧ coverage<1 ∧ absence ∈ {not_searched, evidence_conflict}` |
| LoCoMo 检索文本 | 整段 session summary（写入 `abstract`），不是首句，也不是 Dialogue |
| Static 臂 | `recall_items(limit=5, max_chars=30000)` + 专用 QA 提示，不开 Active Memory |
| Agentic 臂 | `LightHermes.run(stream=False)`，`active_recall=true`，运行时强制搜；注入上下文与搜索返回值已对齐 static 证据预算（`seed_limit=Top-K`、`seed_max_chars=30000`、`item_max_chars=0` 不截断、`search_max_chars=30000`）。这是口径修复（消除两臂证据量不对称），不是按开发集调参 |
| Judge | 一次 CORRECT/WRONG，措辞宽松 |
| Holdout | 本次不跑 |

## 命令

```powershell
.\venv\Scripts\python.exe benchmarks\locomo_light.py --download --mode ab --seed 42 --output logs\locomo_ab_dev.json
```
