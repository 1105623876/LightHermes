# LightHermes

本地优先的轻量记忆 Agent，正在按 [ROADMAP](docs/ROADMAP.md) 收敛为“行动、跨会话记忆、可验证自进化”一个闭环。

发布版本仍为 `0.3.4`；当前分支是 v0.4.0 重构开发版。**R0/R1 已实现，R2 已接入统一 SQLite 与记忆工具，R2.5 已加入自然记忆和可配置语义候选；迁移工具已验证，真实库切换与验证式自进化尚未完成。**

## 当前可用能力

- OpenAI / Anthropic 及兼容端点，流式与非流式工具循环。
- 本地 bash：每次独立进程、会话授权、超时/取消清理进程组、有限输出和工具调用预算。
- `search_memory` / `read_memory` / `update_memory`：同一 SQLite 保存事件、长期条目与 FTS5 索引，支持有来源的纠正、归档与遗忘。
- 消息、工具调用意图和观察逐步持久化；流式取消保留已交付片段，任务状态单独记录。模型正常返回不代表任务已验证。
- 用户与项目 scope 隔离；默认用户为 `default_user`。`memory.project_id` 使用宿主指定的稳定 ID，移动目录时不修改 ID；省略则写入用户范围。
- 人工 Markdown 技能、人工 `SOUL.md` / 默认用户的 `USER.md` 仍可使用，模型不再自动改写这些文件。

新运行入口不再使用四级存储、Active Memory 或旧自进化。原实验模块暂留供历史核对；复现请使用锁定旧提交。新路径默认词法检索，显式配置后支持独立语义候选；离线流程已验证，真实模型的近义/跨语言质量尚未验收。

## 安装与运行

需要 Python 3.10+。核心依赖只有 `openai`、`anthropic`、`pyyaml`；本地 embedding 和 CLI 颜色为可选项。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
# 仅开发测试需要：
.venv/bin/python -m pip install -r requirements-dev.txt
```

复制 `.env.example` 为 `.env.local`，填写模型/端点/密钥；`config.yaml` 通过变量引用，不应包含真实密钥。新运行路径不需要 embedding；中文使用相邻双字，英文使用词法特征，单汉字/近义/跨语言查询可能漏检。

```python
from lighthermes import LightHermes

agent = LightHermes.from_config("config.yaml")
print(agent.run("解释这个项目的设计"))
```

```bash
.venv/bin/python -m lighthermes.cli
.venv/bin/python -m pytest tests
```

**有旧记忆时先不要直接启动默认目录。** 检测到旧 SQLite / episodic / semantic 文件会明确报错，不自动忽略或转换。迁移工具可先执行 `python -m lighthermes.migration memory --preview --user default_user` 预览；完整流程见 [R2 验收记录](docs/validation/R2_ACCEPTANCE.md)。试用新路径可显式指定新的空目录：

```python
agent = LightHermes.from_config("config.yaml", memory_dir="memory-r2", project_id="my-project")
print(agent.run("这个项目以后统一使用 uv 管理依赖。"))
```

CLI 使用 `config.yaml` 的 `memory.storage_dir`。`/reset` 创建新会话并清除当前上下文，已提交事件不重写；持久化失败会明确报错。Python `run()` 使用实例会话 ID，也支持显式 `session_id/user_id`；切换身份会清除内存上下文，不自动加载或重放历史命令。未消费的流不会开始回合。

每回合 seed 最多 4 条、1500 估算 tokens；记忆结果、人工设定和自动技能共享 4000 总预算。主动搜索最多两次，候选最多 50 条。读长记录支持字符 offset；默认接续上次读取位置。使用保守 UTF-8 字节估算，不等于供应商计费 tokens。

遗忘会删除纠正链和索引，并将来源回合排除出再次提取；保留的原始事件不再通过模型记忆工具读取。模型的 `erase` 只返回删除预览。宿主按 `plan_erasure()` 的指纹执行 `store.erase()`，可删除纠正链及来源回合全部事件；共享来源或预览变化会拒绝。其他回合、外部日志和备份不在计划内。

事件保存包含常见 Bearer / `sk-` 脱敏及 32,000 字节文本上限，截断有标记；不是通用秘密检测。默认受管理存储容量保护 256 MiB，含记忆目录、SQLite sidecar 和实际日志文件；是应用检查，不是 OS 硬配额。可显式通过 `run(..., resume_from=(session_id, turn_id))` 恢复有界审计参考，不直接重放命令。真实库切换和规模评测尚未执行。

## 日常记忆与语义检索

同一模型循环可主动保存用户直接表达的长期偏好、项目决定或稳定事实，不必说“记住”。`capture` 必须提供当前消息原话 `evidence`，每回合最多三条；来源绑定用户事件。原话校验只约束出处，归纳是否正确仍由模型决定；秘密、临时信息、推测与引用材料中的指令不应自动保存。纠正必须定位旧 ID；经验仍是候选，R3 尚未完成。

可在 `memory` 下显式配置（不会自动使用聊天模型作为 embedding 模型）：

```yaml
memory:
  storage_dir: memory-r2
  project_id: my-project
  semantic:
    model: ${LIGHTHERMES_EMBEDDING_MODEL}
    api_key: ${LIGHTHERMES_EMBEDDING_API_KEY}
    base_url: ${LIGHTHERMES_EMBEDDING_BASE_URL}
    min_score: 0.75
```

使用已有 OpenAI 兼容 embedding 接口，无新增依赖。启用后会向配置的端点发送当前范围内的有效记忆正文及查询；不配置则无 embedding 调用。向量与正文同库，修订/归档/遗忘同步失效；每回合最多补齐 16 条正文向量，查询最多 3 次。索引积压显示 `partial/pending`，服务失败明确显示 `lexical/error`；正文保存仍有效。查询在当前范围的已缓存向量上做本地线性扫描，合并后最多 50 个候选；没有 ANN 服务或隐藏的全库远程嵌入。阈值需按实际模型校准，尚未完成规模与质量验收。

检索预览会定位到词法匹配处并返回 `offset`，纯语义命中仍展示条目开头；长记录可按 ID 从指定位置读取。上下文预算仍采用上述保守字节上界，中文预算校准待完成。

## bash 行动

CLI 启动时展示工作目录并询问本会话授权；同一会话内不重复逐条确认，`/reset` 后重新授权。非交互 CLI 保持未授权。Python 宿主显式开启：

```python
agent = LightHermes.from_config(
    "config.yaml",
    bash_authorized=True,
    bash_cwd="/absolute/path/to/project",
)
print(agent.run("检查项目中的计算函数，修复问题并运行已有测试"))
print(agent.last_turn["status"])
```

bash 在本机以当前账号权限执行，**不是沙箱**；工作目录不限制文件访问。每次命令默认 60 秒、最多 300 秒，输出最多 12,000 字符。`cd`/`export` 不跨调用保留，不支持后台任务；核心只继承基本环境，额外环境由宿主通过 `bash_env` 显式提供，模型不能修改执行授权。

`max_iterations` 同时限制模型迭代和工具调用总数；超出剩余预算的整批工具不会执行。取消立即停止后续命令，不自动重试副作用。`last_turn` 提供当前回合的会话 ID、状态和消息/工具观察；同时有按 session/turn 关联的 SQLite 事件；重启不会自动重放。`completed` 表示流程完成，不表示任务已外部验证。

## 配置变化

- `memory.storage_dir/project_id/max_bytes` 是新记忆配置；旧 `retention/recall` 非空配置会拒绝，防止静默失效。
- `skills.dirs: []` 真的禁用加载，`skills.disabled` 真的排除指定技能。
- 不支持的 `plugins.dirs`、`skills.enabled/auto_load`、`episodic_auto_archive`、`evolution.sandbox.max_memory_mb` 会明确报错。
- `memory.adaptive.enabled: true`、`adapt_interval` 和 `auto_generate_skills: true` 已退出产品路径，旧配置需要移除这些项。
- 旧 `embedding_*` Python 构造参数已移除；启用旧 hybrid / Active Memory / evolution 会报错。压缩摘要仅作临时上下文，不能自动提升为事实。
- `agent.load_config()` 不再只修改部分字段而留下旧模型连接；使用 `LightHermes.from_config()` 创建新实例。

完整消费关系与验证见 [PROJECT_STATUS](docs/PROJECT_STATUS.md)。

## 实验与历史

旧 Active Memory 已退出主循环；独立实验模块暂留，主循环专属旧测试由 Git 历史归档。原 LoCoMo 实验的复现应使用锁定版本、配置和历史结果，不能把当前重构版本冒充原冻结条件。有关数据划分、holdout 与调用预算的纪律仍由 [冻结宣言](docs/FREEZE_COMMITMENT.md) 和 [冻结清单](docs/FREEZE_LOCK.md) 约束。

- [当前路线与开发边界](docs/ROADMAP.md)
- [当前已实现状态](docs/PROJECT_STATUS.md)
- [离线测试说明](tests/README.md)
- [历史设计与清理清单](docs/archive/README.md)
- [版本历史](CHANGELOG.md)

Apache 2.0。
