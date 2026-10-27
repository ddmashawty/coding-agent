# 里程碑与验收

一次只做一个里程碑。验收通过再进下一个。每个里程碑开一个新对话，开头写：做 Mx，先读 docs/milestones.md。

完整规格见 [PROMPT.md](../PROMPT.md)。

## M1：provider + loop + read + bash

验收：

- 用假 provider 跑通多轮工具调用的单测。
- `scripts/probe_deepseek.py` 跑通；脱敏后的真实响应存成夹具；`test_deepseek_parse` 只用这些夹具。
- 用真实 DeepSeek 完成一个至少两轮工具调用的任务（例如读文件再跑命令并回答）。
- M1 已实现：`finish_reason=length` 时不执行其中的工具调用。完整截断测试留到 M2。

本里程碑不做：write、edit、submit、会话 JSONL、遥测、TUI、Docker、水位线重建。

## M2：write、edit、会话、截断、submit

验收：

- 单测覆盖截断、恢复、edit 匹配不唯一时报错。
- 会话文件为 `.agent/sessions/<id>.jsonl`，目录可配置。默认新建会话；`--continue` 才恢复最近一个。cli 启动时不要自动恢复。
- submit 只进 `headless_tools()`，顺序固定为 `read, write, edit, bash, submit`。交互工具集不含 submit。
- 恢复时若最后一条助手消息带未应答的 `tool_calls`：补合成错误结果（`会话在执行前中断，工具未执行`），不要重新执行。
- JSONL 最后一行写了一半：忽略并警告，之前的条目完好。
- LocalExecutor 子进程环境不含 `DEEPSEEK_API_KEY`（`printenv`）。`redact` 只替换精确的密钥值，不改 `reasoning_content` 里的其他内容。
- 用探测脚本对比两种截断策略（去掉 `tool_calls` vs 保留并返回错误结果），结论写入 `NOTES.md`。

M3 才会做：headless 把会话放到 `--out` 目录，避免污染目标仓库的 git diff。

## M3：事件流、遥测、headless

验收：

- 在一个带 bug 的小仓库上，`agent0 run --task ... --cwd ... --out ...` 修复并输出 `patch.diff`、`events.jsonl`、`telemetry.json`。会话写到 `--out/sessions/`，不写进目标仓库。
- `telemetry.json` 在 finally 里写；内容可从 `events.jsonl` 重新算出（`compute_telemetry`）。含 `outcome`（`submitted` / `no_submit` / `max_steps` / `error`）和起点 commit。
- 启动前必须是 git 仓库；默认工作区干净，`--allow-dirty` 才放行。cwd 不是 git 仓库：启动失败。
- 退出码：0 成功（submit），1 崩溃，2 启动检查失败，3 超过 max_steps，4 没 submit 就停。交互 `agent0 --task` 并存：同一套 EventLog 和遥测写到该会话目录；模型正常说完退出 0。
- `patch.diff` 含未跟踪新文件，且不改目标仓库 index：临时 `GIT_INDEX_FILE`，`read-tree HEAD`，`git add -A`（排除 `.agent/`），`git diff --cached HEAD`。
- 启动时把 `.agent/` 追加进 `.git/info/exclude`（不改 index）。只写 artifacts 的运行后 `git status --porcelain` 为空。
- `--no-rebuild` 可解析，M3 不实现重建。
- `max_steps` 单位是模型调用轮数。
- 软线/硬线按「越过一次算一次」计数。重复读同一文件：仅当两次读之间内容未变化才计数。重试已失败命令：仅当同一命令上次非 0 且两次之间没有成功的 write/edit 才计数。

单测用假 provider。真实 DeepSeek 验收：对 `tests/fixtures/buggy_repo` 跑 headless。

## M4：状态文件、水位线、重建上下文

验收：

- 单测证明重建后状态文件包含所有改过的文件、跑过的命令和原始报错的指针。
- 重建没有拆散任何一对工具调用和结果。
- `--no-rebuild` 可用。
- 用真实 DeepSeek 在思考模式下验证：重建后的上下文能被接口接受，不返回 400（必须带回 `reasoning_content`）。

## M5：简单 TUI

验收：能流式输出、能中断、显示 token 水位，bash 命令需要确认。

## M6：DockerExecutor 与 SWE-bench Verified Mini

验收：先跑通 1 题，再跑 10 题，生成 predictions 文件。打分一律使用官方评测工具，不要自己重写评测逻辑，先查官方文档确认用法。
