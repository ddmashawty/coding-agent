# NOTES

未实现的想法和实现时对照文档的备注。

## DeepSeek 流式 usage 块

探测夹具（`tests/fixtures/deepseek/stream_text.sse`）确认：设了 `stream_options.include_usage` 之后，前面的块 `usage` 为 `null`，`data: [DONE]` 前最后一块同时带 `finish_reason` 和完整 `usage`，`choices` 仍有一个元素。没有单独的空 `choices` usage 块。provider 两种都收。

usage 原始字段名：`prompt_tokens`、`completion_tokens`、`total_tokens`、`prompt_cache_hit_tokens`、`prompt_cache_miss_tokens`，另有 `prompt_tokens_details.cached_tokens` 和 `completion_tokens_details.reasoning_tokens`。

## 思考模式回传

带 `tools` 的请求必须回传历史里**所有**助手消息的 `reasoning_content`，包括没有工具调用的那一轮。只回传「带 tool_calls 的助手消息」不够，会 400。

## 截断后如何回传（探测结论）

`scripts/probe_deepseek.py` 用真实思考模式 + tools 对比了两种后续请求（夹具 `tests/fixtures/deepseek/truncation_compare.json`）：

1. **去掉 tool_calls**：助手消息只留 `content` / `reasoning_content`，再跟一条 user 错误说明。HTTP 200，模型会重发工具调用。
2. **保留 tool_calls 并返回错误 tool 结果**：助手消息原样带回 `tool_calls`，再跟 `role=tool` 的错误结果。HTTP 200，模型同样会重试。

两种都被接口接受，都不 400。v0 继续用做法 1：截断响应里的 tool_calls 不写入会话、不执行。这样不变量 2（截断不执行）和不变量 3（每个已记录的 tool_call 都有结果）同时成立；截断时 arguments 可能不完整，不值得落成正式调用对。

## SWE-bench Verified Mini（M6 对照官方文档）

- 50 题 ID 来自 `princeton-pli/hal-harness` 的 `swebench_verified_mini_task_ids.txt`（25 django + 25 sphinx）。HAL/HF 都写明这是 SWE-bench Verified 的子集。打分用 `princeton-nlp/SWE-bench_Verified` + `--instance_ids`，见 https://www.swebench.com/SWE-bench/guides/evaluation/ 。
- 官方实例镜像：`WORKDIR /testbed/`；conda 装在 `/opt/miniconda3`，环境名 `testbed`。env Dockerfile 把 `source /opt/miniconda3/etc/profile.d/conda.sh && conda activate testbed` 写进 `/root/.bashrc`。`docker exec` 不是 login shell，必须自己 source。
- 远程镜像名（`--namespace swebench`）：`swebench/sweb.eval.x86_64.<id.lower()>`，并把 `__` 换成 `_1776_`。
- `--limit 1` = `django__django-11790`（小的表单回归）。`--limit 10` 种子 2026，每仓库抽 5 题，列表在 `data/swebench_verified_mini.json`。
- 评测命令钉在 `swebench==4.1.0`：`--namespace swebench` 拉 Hub 镜像（空 namespace 才会本地构建，且不能和 `--force_rebuild` 并用）；`--cache_level instance --clean False` 保留实例镜像。默认 `env` 会删掉本次新建的 `sweb.eval.*`。5.x CLI 去掉了这两个参数，所以不跟最新版。完整命令在 `docs/swebench.md`。
- HuggingFace `datasets-server /filter` 对 `instance_id='...'` 返回 422（invalid symbols）。题目行改走 `/rows` 分页，命中后写入 `data/cache/swebench_verified/`。
- `uv sync --group swebench` 直连 PyPI 会卡在 pyarrow/numpy/pandas 大轮子下载。用环境变量 `UV_DEFAULT_INDEX`，不要写进 pyproject / uv.lock / 仓库 uv.toml。
- `--source epoch` 从 GHCR 拉再 tag 成官方名。作者称与原版一致，我们未验证。等 Hub 的 11880 拉完再试。
