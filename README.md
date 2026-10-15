# LightHermes

一个能使用 bash、记住跨会话信息，并在验证后复用任务经验的轻量 Agent。

核心保持一条“模型 → 工具 → 观察”循环。跨会话记忆和任务经验共用 SQLite，事实、来源、修订与索引由同一条运行路径管理。自进化通过“提炼候选 → 独立试用 → 宿主认可 → 后续复用”实现。

**当前是 v0.4.0 重构开发版，包版本仍为 `0.3.4`。** 行动、记忆和显式学习闭环已可用；R4.2 向量存储优化完成，R4.3 学习证据修复完成，真实失败经验的收益对照仍待执行。召回质量和跨任务收益尚未全部通过验收，开发依据见 [ROADMAP](docs/ROADMAP.md)。

## 当前可用能力

- OpenAI / Anthropic 及兼容端点，流式与非流式工具循环。
- 本地 bash：每次独立进程、会话授权、超时/取消清理进程组、有限输出和工具调用预算。
- `search_memory` / `read_memory` / `update_memory`：同一 SQLite 保存事件、长期条目与 FTS5 索引，支持有来源的纠正、归档与遗忘。
- 自然记忆与经验学习：主循环可保存用户直接表达的长期偏好和项目决定；显式 `learn` 生成经验候选，独立试用并认可后才进入日常召回，支持撤回。
- 消息、工具调用意图和观察逐步持久化；流式取消保留已交付片段，任务状态单独记录。模型正常返回不代表任务已验证。
- 用户与项目 scope 隔离；默认用户为 `default_user`。`memory.project_id` 使用宿主指定的稳定 ID，移动目录时不修改 ID；省略则写入用户范围。
- 人工 Markdown 技能、人工 `SOUL.md` / 默认用户的 `USER.md` 仍可使用，模型不再自动改写这些文件。

默认使用词法检索和有预算的短片段召回；语义检索需要显式配置，经验学习默认关闭。运行路径为 `LightHermes → RuntimeMemory → MemoryStore`，核心依赖仍只有三个。旧 Active Memory 等实验模块的保留与复现边界见文末。

## 安装与运行

需要 Python 3.10+。在仓库根目录执行；核心依赖为 `openai`、`anthropic`、`pyyaml`。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

首次配置时，将 [.env.example](.env.example) 复制为 `.env.local`，填写模型、端点和密钥；已有配置请保留。`config.yaml` 通过变量引用密钥。基础运行不需要 embedding 服务。

试用重构版时，在 `config.yaml` 的 `memory` 中指定一个新的空目录及稳定项目 ID：

```yaml
memory:
  enabled: true
  storage_dir: memory-v04
  project_id: my-project
```

**有旧记忆时先不要直接启动旧目录。** 检测到旧 SQLite / episodic / semantic 文件会明确报错。迁移工具可先执行 `.venv/bin/python -m lighthermes.migration memory --preview --user default_user` 预览；完整流程见 [R2 验收记录](docs/validation/R2_ACCEPTANCE.md)。真实旧库切换尚未执行，新目录可以直接使用。

启动交互式 CLI：

```bash
.venv/bin/python -m lighthermes.cli
```

也可以通过 Python 调用：

```python
from lighthermes import LightHermes

agent = LightHermes.from_config(
    "config.yaml", memory_dir="memory-v04", project_id="my-project"
)
print(agent.run("这个项目以后统一使用 uv 管理依赖。"))
```

CLI 使用 `config.yaml` 的 `memory.storage_dir`。`/reset` 创建新会话并清除当前上下文，已提交事件不重写；持久化失败会明确报错。Python `run()` 使用实例会话 ID，也支持显式 `session_id/user_id`；切换身份会清除内存上下文，不自动加载或重放历史命令。未消费的流不会开始回合。

## 跨会话记忆

同一模型循环可主动保存用户直接表达的长期偏好、项目决定或稳定事实，不必说“记住”。`capture` 必须提供当前消息原话 `evidence`，每回合最多三条；来源绑定用户事件。原话校验只约束出处，归纳是否正确仍由模型决定；秘密、临时信息、推测与引用材料中的指令不应自动保存。纠正必须定位旧 ID；模型提炼的经验先保存为候选，经过独立试用与宿主认可后激活。

每回合先召回少量相关短片段（seed），最多 4 条、1500 UTF-8 字节；需要时再由模型调用搜索和读取工具。记忆结果、人工设定和技能共享 4000 字节总预算，主动搜索最多两次。读长记录支持字符 offset，默认接续上次读取位置。字节上界不等于供应商计费 tokens，中文实际 token 开销仍待校准。

遗忘会删除纠正链和索引，并将来源回合排除出再次提取；保留的原始事件不再通过模型记忆工具读取。模型的 `erase` 只返回删除预览。宿主按 `plan_erasure()` 的指纹执行 `store.erase()`，可删除纠正链及来源回合全部事件；共享来源或预览变化会拒绝。其他回合、外部日志和备份不在计划内。

事件保存包含常见 Bearer / `sk-` 脱敏及 32,000 字节文本上限，截断有标记；不是通用秘密检测。默认受管理存储容量保护 256 MiB，含记忆目录、SQLite sidecar 和实际日志文件；是应用检查，不是 OS 硬配额。正文、会话与日志增长都占用容量。可显式通过 `run(..., resume_from=(session_id, turn_id))` 恢复有界审计参考，不直接重放命令。

### 可选语义检索

默认词法检索对中文使用相邻双字、对英文使用词法特征，单汉字、近义和跨语言查询可能漏检。需要语义候选时，在 `memory` 下添加配置；聊天模型不会自动用作 embedding 模型：

```yaml
memory:
  storage_dir: memory-v04
  project_id: my-project
  semantic:
    model: ${LIGHTHERMES_EMBEDDING_MODEL}
    api_key: ${LIGHTHERMES_EMBEDDING_API_KEY}
    base_url: ${LIGHTHERMES_EMBEDDING_BASE_URL}
    min_score: 0.75  # 当前默认值；需按实际数据独立校准
```

使用 OpenAI 兼容 embedding 接口，无新增依赖。启用后会向配置的端点发送当前范围内的有效记忆正文及查询；不配置则无 embedding 调用。向量与正文同库，修订、归档、遗忘同步失效；每回合最多补齐 16 条正文向量、调用 3 次查询 embedding。索引积压显示 `partial/pending`，服务失败显示 `lexical/error`；正文保存仍有效。

查询在当前范围的已缓存向量上做本地 **O(n·d) 精确扫描**，语义通道最多 50 个候选后与词法结果融合。R4.2 已减少向量存储与解码开销，尚未引入树或 ANN。已有小样本验收中，默认阈值 0.75 漏掉了校准跨语言正例，降到 0.46 后又出现难负例误召回；两者都不能当作通用阈值，语义召回质量仍需验证。

既有 schema 4 库保持 JSON 读写，打开时不自动转格式。需要转换时，先关闭其他使用者、备份并确认事务日志空间，再由宿主显式调用 `store.compact_vectors()`。它只在本地无损转换缓存，失败整次回滚，不重新嵌入、不改事实与来源。转换不缩小既有文件；释放出的页面可复用。schema 5 不支持旧版程序直接打开，回退需恢复转换前备份。真实库转换和磁盘压缩仍需单独授权，不由 Agent 工具执行。

检索预览会定位到词法匹配处并返回 `offset`，纯语义命中仍展示条目开头；长记录可按 ID 从指定位置读取。

## bash 行动

CLI 启动时展示工作目录并询问本会话授权；同一会话内不重复逐条确认，`/reset` 后重新授权。非交互 CLI 保持未授权。Python 宿主显式开启：

```python
agent = LightHermes.from_config(
    "config.yaml",
    memory_dir="memory-v04",
    project_id="my-project",
    bash_authorized=True,
    bash_cwd="/absolute/path/to/project",
)
print(agent.run("检查项目中的计算函数，修复问题并运行已有测试"))
print(agent.last_turn["status"])
```

bash 在本机以当前账号权限执行，**不是沙箱**；工作目录不限制文件访问。每次命令默认 60 秒、最多 300 秒，输出最多 12,000 字符。`cd`/`export` 不跨调用保留，不支持后台任务；核心只继承基本环境，额外环境由宿主通过 `bash_env` 显式提供，模型不能修改执行授权。

`max_iterations` 同时限制模型迭代和工具调用总数；超出剩余预算的整批工具不会执行。取消立即停止后续命令，不自动重试副作用。`last_turn` 提供当前回合的会话 ID、状态和消息/工具观察；同时有按 session/turn 关联的 SQLite 事件；重启不会自动重放。`completed` 表示流程完成，不表示任务已外部验证。

## 自进化：验证后复用经验

在配置中开启 `evolution.enabled: true`，或传入 Python 参数 `evolution_enabled=True`。回答照常交付；之后由用户或宿主提供**实际检查结果**，不能把模型“已完成”当验证。下面展示接口顺序，验证说明需要换成真实检查记录：

```python
agent = LightHermes.from_config(
    "config.yaml",
    memory_dir="memory-v04",
    project_id="my-project",
    evolution_enabled=True,
)
reply = agent.run("完成当前任务")
# 宿主实际检查通过后，才记录 verified_success：
receipt = agent.learn("具体检查及结果……", outcome="verified_success")
if receipt["status"] == "candidate":
    experience_id = receipt["entry_id"]
    reply = agent.run("另一个相关任务", trial_experience=experience_id)
    # 宿主确认实际采用该经验，并独立检查新产物通过后：
    agent.learn("实际采用的方法、独立检查及结果……",
                outcome="verified_success", adopted=True)
    agent.review_experience(experience_id, action="approve", reason="认可的适用范围……")
else:
    print(receipt)  # 可能没有可提炼的方法，或提炼失败
```

候选只进入明确选择的试用任务。已激活经验走普通记忆检索；来源包含原任务、工具调用意图与观察、宿主结果和后续试用。仅召回不算采用；`approve` 要求最近一次已采用试用验证成功。宿主确认已采用试用失败时，已激活条目退出召回；也可通过 `review_experience(..., action="revoke", reason="具体原因")` 撤回。

CLI 对应 `/learn success|failure|unknown <具体验证说明>`、`/experiences`、`/trial <ID> <任务>`、`/learn used-success|used-failure <验证说明>`、`/approve <ID> <适用范围与理由>` 和 `/revoke <ID> <理由>`。首次学习最多一次额外模型请求，试用反馈不再提炼；关闭/重复调用不隐式重试。提炼失败保留已经交付的回答，并返回明确状态。

R4.3 已补齐学习证据：从当前回合的已保存事件中配对工具命令/参数与输出，向候选保留两边的来源。最多提供 6 组有界片段，缺失或截断会标记，并提示模型不要据此补编方法；“命令执行成功”不能直接当作任务已验证。

这是显式触发的学习闭环，尚无自动经验激活，也未证明跨任务成功率提升。`verified_success` 表示宿主/用户提供了检查结果，框架不冒充独立裁判。

## 进展与验证

截至 2026-10-15，已记录的最新全量离线回归为 **298 passed**。工程回归、真实模型质量和经验收益分别验收：

| 阶段 | 已完成与结论 | 记录 |
|---|---|---|
| R0–R3：行动、记忆、学习闭环 | 已实现；自然保存与经验试用有真实模型小样本回放，真实旧库切换待执行 | [R2](docs/validation/R2_ACCEPTANCE.md)、[R2.5 / R3](docs/validation/R25_R3_ACCEPTANCE.md) |
| R4：规模与收益 | 完成万条规模、精确 VP-tree 和三配置回放；召回污染与两类经验收益门槛未全部通过 | [R4](docs/validation/R4_ACCEPTANCE.md) |
| R4.1：读取策略 | 三组正式评测均 9/9；按需读取少约 8% tokens、但多 5 次模型请求，保留短片段默认值 | [R4.1](docs/validation/R41_ACCEPTANCE.md) |
| R4.2：向量存储 | 新库使用无损 binary64；同机合成万条 × 1024 维查询 p50 从 1.59 秒降至 0.34 秒，新建库从 244 降至 92 MiB，63 组排名一致 | [R4.2](docs/validation/R42_ACCEPTANCE.md) |
| R4.3：失败经验 | 已修复学习材料缺少实际操作的问题；固定命令回放通过，真实模型失败诊断与独立收益对照待执行 | [R4.3](docs/validation/R43_EVIDENCE.md) |

性能数字来自指定机器和合成数据；固定命令与模拟模型回放验证工程行为，不证明模型学到了方法。下一步重点是 R4.3：在可用且已授权的受限执行环境中，用真实失败形成候选，再检查能否减少新任务中的重复失败，以及是否误用于相邻反例。短片段默认、语义显式配置、经验人工认可继续保持；中文 token 校准和真实旧库迁移仍是独立待办。

开发时运行离线回归：

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests
```

测试使用临时目录与模拟模型，并阻断网络连接；不会调用付费模型或修改真实记忆。真实模型验收需单独授权，入口和复现条件见 [测试说明](tests/README.md)。

## 配置变化

- `memory.storage_dir/project_id/max_bytes` 是新记忆配置；旧 `retention/recall` 非空配置会拒绝，防止静默失效。
- `skills.dirs: []` 真的禁用加载，`skills.disabled` 真的排除指定技能。
- 不支持的 `plugins.dirs`、`skills.enabled/auto_load`、`episodic_auto_archive`、`evolution.sandbox.max_memory_mb` 会明确报错。
- `memory.adaptive.enabled: true`、`adapt_interval` 和 `auto_generate_skills: true` 已退出产品路径，旧配置需要移除这些项。
- 旧 `embedding_*` Python 构造参数已移除；启用旧 hybrid / Active Memory 会报错；evolution.enabled 现在允许显式的验证式学习检查点。压缩摘要仅作临时上下文，不能自动提升为事实。
- `agent.load_config()` 不再只修改部分字段而留下旧模型连接；使用 `LightHermes.from_config()` 创建新实例。

完整消费关系与验证见 [PROJECT_STATUS](docs/PROJECT_STATUS.md)。

## 实验与历史

旧 Active Memory 已退出主循环；其独立实验模块暂留，主循环专属旧测试由 Git 历史归档。原 LoCoMo 实验的复现应使用锁定版本、配置和历史结果，不能把当前重构版本冒充原冻结条件。有关数据划分、holdout 与调用预算的纪律仍由 [冻结宣言](docs/FREEZE_COMMITMENT.md) 和 [冻结清单](docs/FREEZE_LOCK.md) 约束。

- [当前路线与开发边界](docs/ROADMAP.md)
- [当前已实现状态](docs/PROJECT_STATUS.md)
- [离线测试说明](tests/README.md)
- [历史设计与清理清单](docs/archive/README.md)
- [版本历史](CHANGELOG.md)

Apache 2.0。
