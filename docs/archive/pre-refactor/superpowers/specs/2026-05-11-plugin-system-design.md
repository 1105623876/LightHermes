# Phase 3.1 轻量工具与 Channel 插件系统设计

## 背景

v0.3.3 已完成记忆工具计划与 Phase 2.7 发版检查。下一阶段进入 Phase 3 生态扩展，但 LightHermes 仍应保持轻量、安全默认和最小依赖。

本设计借鉴 `nanobot` 的插件发现、显式启停、错误隔离、工具调用前校验和 channel 边界，但不照搬其完整 bus、gateway、entry points、cron、MCP 或多平台 channel 生态。

## 目标

- 支持本地工具插件，让外部 Python 文件能向现有 `ToolDispatcher` 注册工具。
- 支持本地 channel 插件，让外部 Python 文件能注册轻量 `DirectChannel` 风格通道。
- 插件默认关闭，必须在配置中显式启用。
- 插件加载失败默认不阻断主流程，`strict` 模式可切换为启动失败。
- 增加工具调用前运行时参数校验，避免明显错误参数进入工具函数。
- 不新增依赖，不自动安装插件依赖。

## 非目标

- 不实现 Python entry points 插件发现。
- 不实现插件市场。
- 不实现网络 channel、后台监听、bus 或 gateway。
- 不引入 nanobot 的 Schema DSL。
- 不实现 `self_state` 自省工具，只在后续计划中预留。
- 不扩展 provider 或 skill 插件系统。

## 总体架构

新增 `lighthermes/plugins.py` 承担本地插件加载职责：

1. 读取 `plugins.tools` 与 `plugins.channels` 配置。
2. 校验插件目录必须是项目内相对路径，拒绝绝对路径和 `..` 逃逸。
3. 只对 `enabled` 列表中的插件名执行模块导入。
4. 按插件类型分别注册到 `ToolDispatcher` 或 `ChannelRegistry`。
5. 捕获加载异常：默认 warning 跳过，`plugins.strict: true` 时抛出。

工具插件复用现有 `ToolDispatcher`。Channel 插件使用新的轻量 `ChannelRegistry`，只负责注册、覆盖、列出和获取 channel，不负责异步生命周期或后台监听。

## 配置结构

```yaml
plugins:
  strict: false
  tools:
    dirs:
      - plugins/tools
    enabled: []
  channels:
    dirs:
      - plugins/channels
    enabled: []
```

规则：

- `enabled: []` 时不会导入任何插件模块。
- 插件名来自文件名 stem，例如 `plugins/tools/hello.py` 的插件名是 `hello`。
- 只有插件名出现在对应 `enabled` 列表中才会加载。
- 第一版只支持项目内相对路径。

## 工具插件 API

工具插件支持两种入口。

### 简单入口：`@tool` 自动收集

```python
from lighthermes import tool

@tool(name="hello", description="Say hello")
def hello(name: str) -> str:
    return f"Hello {name}"
```

加载器导入模块后，自动发现带工具元数据的函数并注册到 `ToolDispatcher`。

### 复杂入口：`register(dispatcher)`

```python
def register(dispatcher):
    dispatcher.register_tool(my_tool)
```

如果模块提供 `register(dispatcher)`，加载器优先调用它，不再自动收集模块内的 `@tool` 函数，避免重复注册。

同名工具沿用现有覆盖语义：后注册覆盖先注册，并记录 warning。

## Channel 插件 API

Channel 第一版只验证本地通道边界，不做网络服务或后台生命周期。

基础接口保持轻量：

```python
class BaseChannel:
    name: str

    def send(self, message: ChannelMessage) -> None:
        raise NotImplementedError

    def receive(self) -> ChannelMessage | None:
        raise NotImplementedError
```

插件支持两种入口。

### 简单入口：暴露 channel 对象或 channel 类

```python
from lighthermes.channels import DirectChannel

channel = DirectChannel(name="local_debug")
```

### 复杂入口：`register_channels(registry)`

```python
def register_channels(registry):
    registry.register(DirectChannel(name="local_debug"))
```

如果模块提供 `register_channels(registry)`，加载器优先调用它。否则加载器尝试收集模块级 `channel` 对象。

`ChannelRegistry` 职责：

- `register(channel)`：注册或覆盖 channel。
- `get(name)`：按名称获取 channel。
- `list_channels()`：列出已注册 channel 名称。
- 隔离插件加载失败。

## 工具运行时参数校验

借鉴 nanobot 的 `prepare_call` 思路，在工具执行前做轻量校验：

- 工具参数必须是 JSON object。
- 必填参数缺失时返回错误。
- 简单类型不匹配时返回错误。
- 校验错误作为工具结果返回给模型，而不是抛出到主流程。
- 工具函数异常继续由 dispatcher 捕获并返回错误信息。

不引入 `StringSchema`、`ObjectSchema` 等 Schema DSL，继续以现有函数签名和生成的 JSON schema 为准。

## 安全与错误处理

- 默认不加载插件。
- 不自动安装依赖。
- 插件加载器只读取 `plugins.*` 配置，不把完整配置对象传给插件。
- 插件目录限制在项目内相对路径。
- 加载失败默认记录 warning 并跳过。
- `plugins.strict: true` 时任一启用插件加载失败都会中断初始化。
- 坏插件不能影响未启用插件，也不能影响内置工具默认路径。

## Core 集成

`LightHermes` 初始化时在内置工具注册后加载插件：

1. 初始化 `ToolDispatcher`。
2. 注册内置工具。
3. 初始化 `ChannelRegistry`。
4. 根据 `plugins.tools` 加载工具插件。
5. 根据 `plugins.channels` 加载 channel 插件。

插件默认关闭时，现有行为和测试基线不应变化。

## 测试计划

### PluginLoader

- `enabled: []` 时不导入插件文件。
- 只加载 enabled 列表中的插件。
- 拒绝绝对路径和 `..` 路径。
- 加载失败时默认 warning 跳过。
- strict 模式下加载失败抛错。

### 工具插件

- `@tool` 自动收集能注册工具。
- `register(dispatcher)` 能注册工具。
- 同时存在 `register()` 和 `@tool` 时只走 `register()`。
- 参数校验能拦截非 object、缺必填和简单类型不匹配。

### Channel 插件

- `DirectChannel` 样例插件可被显式启用并注册。
- 未启用时不会加载。
- `ChannelRegistry` 能 list/get channel。

### Core 集成

- `LightHermes` 初始化时按配置加载工具插件和 channel 插件。
- 插件默认关闭时不影响现有测试基线。

## 文档计划

- README 增加 Phase 3.1 插件系统说明。
- ROADMAP 将 Phase 3.1 细化为工具插件与轻量 channel 插件。
- PROJECT_STATUS 增加 v0.3.3 后下一步设计状态。
- 后续计划预留只读 `self_state` 自省工具：查询模型、memory/tools 状态和统计信息，但不在 Phase 3.1 实现。
