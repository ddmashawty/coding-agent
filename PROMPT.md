# v0 启动 Prompt：终端 Coding Agent

Oct 25, 2026 · @ddmashawty

把下面的提示词整段交给 coding agent，它会按六个里程碑逐步搭出 v0，每个里程碑结束就停下等你验收。

## 使用方法

- 新建一个空仓库，把本文导出为 Markdown，存成 PROMPT.md，按下一节的方式放进 Cursor 的规则文件，并从 M1 开始。
- 一次只做一个里程碑，验收通过再进下一个，不要让它一口气做完。
- DeepSeek 接口的字段细节要它对着官方文档核对，不要让它凭印象写。

## 在 Cursor 里怎么跑

把规则放进 Cursor 的规则文件，里程碑单独存放，每个里程碑开一个新对话。

- 用 Cursor 的 WSL 连接打开仓库，保证 Python、uv 和 Docker 都在 WSL 里运行。具体入口我没有查证，找不到就看 Cursor 文档。
- 把“任务、硬约束、架构、不变量、工作方式”这几节存成 `.cursor/rules/agent0.mdc`，文件开头写 `alwaysApply: true`。规则每个会话都会带上，所以早期的要求不会被冲淡。
- 把“里程碑与验收”存成 `docs/milestones.md`，不要放进规则，因为每次只需要其中一个里程碑。
- 每个里程碑开一个新对话，开头只写：做 M1，先读 docs/milestones.md。Cursor 在上下文将满时会摘要旧对话，新对话能避免这一点。
- 每个里程碑先用 Plan 模式（Shift+Tab 切换）出计划，你确认文件清单和测试后，再切到 Agent 模式执行。这正好对应提示词里“先列出文件和测试、等我确认”。
- 执行完先让它跑测试，再自己看 diff，通过后再进下一个里程碑，不要只信它的总结。
- 新建 `.cursorignore`，写入 `.agent/`、`runs/` 和 `.venv/`，避免大量日志和产物被索引，挤占上下文。
- 每次只附 2 到 3 个相关文件，不要附整个目录。
- M1 和 M4 最难（loop 和重建），用你能选的最强编码模型；其余里程碑可以用更省的。

以上 Cursor 的用法来自第三方使用指南，截至 2026 年年中，Cursor 更新很快，界面和名称可能已经不同。

## 提示词正文

### 任务

你要在 WSL 上用 Python 实现一个极简终端 coding agent 的 v0，暂用代号 agent0。它的特色是：平时只追加上下文，到达硬线时用“状态文件 + 最近几轮”一次性重建上下文，原文始终留在磁盘上可以恢复。结构上借鉴 Pi 的 agent loop，但不借鉴它的扩展系统、skills、主题和包生态。

使用者只有我一个人，用来修 bug、实现功能、重构、写测试。这个项目的价值来自我每天真的在用它，所以稳定、可恢复、日志完整，比功能多更重要。

### 硬约束

- Python 3.11 以上，用 uv 管理依赖。依赖尽量少，新增任何依赖前先问我。
- 模型是 DeepSeek-V4.1-Flash-1017，走 OpenAI 兼容接口，窗口 1M。模型名、base_url、api key 从配置文件和环境变量读取，不要写死。provider 要抽象成接口，但 v0 只实现 DeepSeek。
- 工具只有 read、write、edit、bash，另有只在 headless 模式使用的 submit。不要加搜索工具、MCP、子 agent、skills、插件、plan 或 todo 工具。
- 工具串行执行：按模型给出的顺序，一个完成再做下一个。
- system prompt 要极短，目标不超过 1000 token，自己写，不要抄别家的长提示词。
- DeepSeek 接口的细节必须对照官方文档核对，包括工具调用的格式、finish_reason，以及 usage 里缓存命中和未命中的字段名。解析必须保留原始 usage 字段。流式请求必须要求返回 usage（`stream_options.include_usage`），并处理结尾单独的 usage 块（以及 usage 附在最后内容块上的情况）。
- DeepSeek V4 默认开思考模式。带工具调用的助手消息必须把 `reasoning_content` 原样回传，否则 400。`messages.py` 要保存并回传该字段；假 provider 要模拟这条规则（缺字段就拒绝）；`agent.toml` 加 `thinking` 选项，默认 `enabled`。
- 先写 `scripts/probe_deepseek.py`，分别打印流式和非流式（含工具调用）的原始响应，把脱敏后的真实响应存成夹具；解析测试只用这些夹具，不要用凭文档想象的 JSON。
- API key 从环境变量 `DEEPSEEK_API_KEY` 读取。`.env` 进 `.gitignore`。key 不得出现在会话 JSONL、事件、遥测和日志里，并加测试。
- bash 加超时（默认 120 秒，可配置）和测试。
- 请求构造必须确定：同一状态连续构造两次请求，前缀逐字节一致，工具按固定顺序发送。
- 终端界面用 prompt_toolkit 加 rich，保持简单。
- 每个模块都要能单测。用 pytest，并提供一个假 provider 供测试使用，测试里不要调用真实 API。
- 不要自作主张加功能。需求之外的想法写进 NOTES.md，不要实现。

### 架构

- agent/loop.py：双层循环。内层处理工具调用和用户插队消息（steering），外层预留后续消息（follow-up）的接口，v0 不实现。事件包括 agent_start、turn_start、message_start、message_end、tool_execution_start、tool_execution_end、turn_end、agent_end。
- 钩子：transform_context（每次调用模型前改写消息列表，不改会话原文）、before_tool_call（可阻止或改写参数，用于 bash 权限确认）、after_tool_call（可覆盖结果，用于记录机械事实）、after_turn（回合结束后做水位线检测、可替换上下文或决定停止）。
- agent/messages.py：内部消息类型可扩展，进模型前才转成 LLM 消息，自定义类型不能泄漏进请求。必须保存并原样回传 reasoning_content。
- providers/：一个基础接口，加 deepseek.py。要支持流式输出、工具调用，并解析 usage（保留原始字段：输入、输出、缓存命中、缓存未命中）。假 provider 在带 tools 的请求里若助手消息缺 reasoning_content 必须拒绝。
- scripts/probe_deepseek.py：探测流式/非流式（含工具调用）原始响应，写出脱敏夹具。
- tools/：read、write、edit（精确字符串替换，匹配必须唯一，返回 diff）、bash、submit。bash 输出过长时只保留头尾，完整内容落盘到 .agent/artifacts/ 并在结果里写明路径，模型可以用 read 取回。bash 默认超时 120 秒，可配置。
- executors/：统一的执行器接口（运行命令、读文本、写文本），实现 LocalExecutor 和 DockerExecutor。所有工具都只通过执行器访问文件系统和 shell。
- session.py：会话存成 `.agent/sessions/<id>.jsonl`（目录可配置），每条有 id 和 parent_id，只追加；默认新建；`--continue` 恢复最近一个。cli 启动不自动恢复。M3 起 headless 会话写到 `--out`。
- state.py：状态文件 .agent/state.md，订阅事件，自动记录机械事实。格式见下。
- context.py：水位线和重建上下文。
- telemetry.py：遥测，每个会话写一份 JSONL。
- cli.py：交互模式（简单 TUI）和 headless 模式。

### 状态文件格式（.agent/state.md）

- 机械事实（由 harness 自动写，模型不用管）：读过的文件（路径、次数）；改过的文件（路径、次数、最近一次 diff 的磁盘指针）；跑过的命令（命令、退出码、一行摘要、完整输出的磁盘指针）；报错原文只保存到 .agent/artifacts/，状态里只留指针。
- 判断事实：v0 只保留一个空标题，v1 才写入。

### 水位线与重建

- 软线 = min(窗口的 50%, 60K token)。v0 只在遥测里记录“到达软线”这个事件，不做别的。
- 硬线 = min(窗口的 70%, 90K token)。到达后，在下一次调用模型之前重建上下文：system prompt，加上由状态文件渲染出的摘要消息（机械事实和磁盘指针），加上最近 6 轮原文。切分点必须落在回合边界，不得拆开一对工具调用和它的结果。
- 重建只改变发给模型的视图。会话 JSONL 里要追加一条 rebuild 记录，原条目一律不动。
- 重建之后继续只追加，直到再次到达硬线。
- 提供命令行开关 --no-rebuild，关闭后退回纯追加模式，用来对比。

### 遥测字段

每个会话记录：耗时、轮数、工具调用次数；token 的输入、输出、缓存命中、缓存未命中；到达软线和硬线的次数；重复读同一文件的次数；重试已经失败的同一条命令的次数；用户接管次数。

### 命令行

- 交互：agent，进入简单 TUI，流式输出，可中断，显示工具调用、diff 和当前 token 水位。bash 命令默认需要我确认，可以配置白名单。
- 无界面：agent run --task 文本 --cwd 目录 --out 目录 [--no-rebuild]。不需要确认，由执行器负责隔离。输出 patch.diff、events.jsonl、telemetry.json；模型调用 submit 后以退出码 0 结束，崩溃或超过步数上限则退出码非 0。默认步数上限 100，可配置。

### 必须遵守的不变量

1. 会话 JSONL 只追加，永不修改或删除已有条目。
2. 响应因长度被截断（finish_reason 为 length）时，其中的工具调用一律不执行，返回错误让模型重发。
3. 每个工具调用必有对应的结果，结果按调用顺序写回。
4. 每一次工具调用都由 harness 记录进状态文件，不依赖模型自己记。
5. 一批工具结果全部带终止标记时提前结束（submit 使用）。
6. 出错、中断、崩溃都不能丢失已经写入的会话和状态。
7. reasoning_content 在会话 JSONL 里逐字保留并原样回传。
8. 请求构造是确定的，system prompt 不含时间戳或随机内容。

### 默认配置（agent.toml，全部可改）

- context_window = 1000000
- 软线：比例 0.5，绝对上限 60000
- 硬线：比例 0.7，绝对上限 90000
- keep_turns = 6
- 连续失败阈值 3 和 5：v0 只记录，不触发任何动作
- thinking = "enabled"
- bash_timeout_seconds = 120

### v0 范围

- 包含：loop、四个工具加 submit、DeepSeek provider、会话 JSONL 与恢复、机械事实记录、软线与硬线、重建上下文、遥测、简单 TUI、headless 模式、本地与 Docker 执行器。
- 不包含：判断事实的提议与确认、状态跃迁触发、/checkpoint 命令、会话分支界面、follow-up 队列、并行工具、多模型。

### 里程碑与验收

- M1：provider 加 loop 加 read 和 bash。验收：用假 provider 跑通多轮工具调用的单测；探测脚本跑通；真实响应存成夹具；用真实 DeepSeek 完成一个至少两轮工具调用的任务。截断不执行工具在 M1 实现，M2 再补完整测试。
- M2：write、edit、会话 JSONL 与恢复、截断即失败、submit 与终止标记。验收：单测覆盖截断、恢复、edit 匹配不唯一、恢复时未应答 tool_calls 合成错误、半行 JSONL、子进程环境不含 key、redact 只替换精确密钥；探测脚本对比截断策略并写入 NOTES.md。
- M3：事件流、遥测、headless 模式。验收：在一个带 bug 的小仓库上，headless 修复并输出 patch.diff 和遥测。
- M4：状态文件、水位线、重建上下文。验收：单测证明重建后状态文件包含所有改过的文件、跑过的命令和原始报错的指针；重建没有拆散任何一对工具调用和结果；--no-rebuild 可用。用真实 DeepSeek 在思考模式下验证，重建后的上下文能被接口接受，不返回 400。
- M5：简单 TUI。验收：能流式输出、能中断、显示 token 水位，bash 命令需要确认。
- M6：DockerExecutor 与 SWE-bench Verified Mini 的运行脚本。验收：先跑通 1 题，再跑 10 题，生成 predictions 文件。打分一律使用官方评测工具，不要自己重写评测逻辑，先查官方文档确认用法。

### 工作方式

- 每个里程碑开始前，先列出要新建的文件和要写的测试，等我确认再动手。
- 完成后汇报：改了什么、怎么跑测试、哪些没做、哪些地方你不确定。
- 不确定就问我，不要猜。
