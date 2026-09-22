# R2 开发验收记录

日期：2026-09-22。基线 `525d489` 已推送。本轮使用用户明确授权的 `.env.local` 模型 `grok-4.6`，只发送合成案例，未向模型发送真实记忆。真实库仅在本机临时目录做转换预览。

## 结论

当前离线行为检查通过，已发现的实际模型失败完成修复和定向复验。**不宣称最终版本已经单轮跑出 12/12，也不宣称稳定成功率。** 真实数据切换尚未执行，因此 R2 的实际迁移事项仍未勾选；R3 尚未开始。

| 检查 | 结果与边界 |
|---|---|
| 全套离线回归 | 273 passed / 3.00s；无网络、临时数据 |
| 初始真实回放 | 10/10，19 次调用；当时项目隔离只检查没有泄漏项目 A，尚未严格检查无关全局 seed |
| 强化真实回放 | 11/12，20 次调用；覆盖长记录保存与 `read_memory` 尾部读取、流式回答。失败项为项目 B：零注入成立，但模型在空回包后多次寻工具，耗尽预算 |
| 修复后定向复验 | 4/4，8 次调用；重新准备全局偏好、纠正、项目 A 记录，再验证项目 B；项目 B 正常完成，零 seed，无跨项目泄漏 |
| 真实库转换预览 | 7 文件 / 44,636 bytes → 3 来源事件、2 candidate、0 active；SQLite integrity_check=ok，源文件哈希不变，临时副本已删除 |

三次真实回放合计 **47 次调用**，已记录 usage **至少 51,791 tokens**。首次回放未采集流式末尾 usage，所以合计是下界；后续已修复末尾 usage 采集。每次调用输出上限 600 tokens、超时 45 秒、SDK 重试 0、每批总上限 32 次；没有额外模型裁判。未查询供应商价表，不报告猜测金额。

完整合成输出及失败保留在 [r2-live.json](r2-live.json)，可运行入口为 [scripts/r2_acceptance.py](../../scripts/r2_acceptance.py)。它必须显式传 `--live`，不被 pytest 自动执行。定向复验通过 `--cases remember correction project_a_write project_b_isolation` 指定，不能省略必要准备步骤。

## 本轮修复与交付

- **弱相关污染**：旧中文单字 OR 匹配能让“我的默认编程语言”进入“今天的天气”上下文。新库 schema 3 对中文使用相邻双字，英文复用现有分词并去少量功能词；入库与查询一致，旧 R2 索引事务性重建。旧冻结实验分词不变。近义、跨语言、单汉字查询仍是词法限制，不通过放宽范围掩盖漏检。
- **空结果歧义**：搜索区分 `no_match`、`already_in_context`、`budget_exhausted`；系统提示要求依据不足时说明未知，不用 bash 绕过记忆范围。零注入仍可为 0，错误不伪装成空结果。
- **一致性与增长**：同范围、同 kind/content/status 精确去重，不因重复写入增加证据来源。数据库目录、SQLite sidecar、实际日志 handler 文件均计入应用容量，接近上限暂停非必要候选。`/memory` 报物理总量与分类逻辑正文大小，二者不混加；无 embedding 缓存，不建立缓存清理后台服务。
- **删除预览**：`plan_erasure()` 列精确纠正链及来源回合全部事件；共享来源阻塞、预览变化阻塞。宿主 `erase(..., approved_fingerprint=...)` 执行同事务删除。模型 `erase` 只返回预览，不能替宿主批准扩大范围。其他回合、外部日志、导出、备份不在该计划内，也不承诺取证级物理抹除。
- **显式恢复**：`run(..., resume_from=(session_id, turn_id))` 按当前 scope 取有界审计参考，计入记忆预算；先核对状态，不直接重放工具。已遗忘回合/其他用户与项目拒绝读取。
- **完成语义**：模型 length/content_filter 停止记为 incomplete；存储故障中止，流式取消记录部分输出；流式末尾 usage 不再漏计。

## 迁移使用与边界

```bash
# 只读文件清单和哈希
.venv/bin/python -m lighthermes.migration memory
# 本机临时转换预览；不会保留目标或改动旧库
.venv/bin/python -m lighthermes.migration memory --preview --user default_user
# 仅在确定真实目标和归属后执行；本轮没有执行此命令
.venv/bin/python -m lighthermes.migration memory --target memory-r2 --user default_user --apply
```

导入必须写入旧目录之外的新目录，先制作并核验源快照，失败不发布目标。完成后保留 `legacy_sources/` 和 `import.json`，后者含原路径、哈希、来源 ID、条目 ID 与 scope 映射。重复同一快照导入为 no-op，来源变更或目标冲突明确拒绝，不自动合并。

旧数据库中的 user_id 原样保留，未归属的 Markdown 使用显式 `--user`；不隐式合并 `default/default_user`。人工文件原样保留；SOUL 复制为设定，USER 仅在明确归属 default_user 时复制为默认用户设定，其他归属只保留快照，避免跨用户注入。未知字段/文件/表保留，BLOB 字段在事件中以 base64 保存。所有导入条目为 candidate，需要审阅后激活。旧库不会因此自动成为 active，也不自动修改 `config.yaml` 的 storage_dir。

真实预览快照：`ec13ff7f0af5d53cc186e3caac28f804f3157a2d68aff1fee505899f647cb4e9`。下一次真实应用前会重新核验；不把本次预览当作对未来已变化数据的批准。

## 后续门槛

1. 确定真实库切换目标与无归属数据归属后，执行已预览的迁移并审阅候选。
2. R3 才接入任务验证、候选试用/激活和撤回；当前模型返回完成不代表外部任务通过。
3. R4 再做 100/1,000/10,000 条规模回放、难负例、近义/跨语言质量和收益对照；本轮的小样本不替代这些验证。
