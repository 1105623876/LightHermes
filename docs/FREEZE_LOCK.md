# A/B 冻结清单（开发集）

**日期**: 2026-08-15  
**状态**: 已锁。修改须同步 ROADMAP，不得按开发集个例拧参。  
**范围**: LoCoMo 40 题分层开发集，**不是 holdout**。

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
| Static 臂 | `recall_items` + 专用 QA 提示，不开 Active Memory |
| Agentic 臂 | `LightHermes.run(stream=False)`，`active_recall=true`，运行时强制搜 |
| Judge | 一次 CORRECT/WRONG，措辞宽松 |
| Holdout | 本次不跑 |

## 命令

```powershell
.\venv\Scripts\python.exe benchmarks\locomo_light.py --download --mode ab --seed 42 --output logs\locomo_ab_dev.json
```
