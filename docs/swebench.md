# SWE-bench Verified Mini

评分只用官方 harness，不重写 pass/fail。实例镜像从 Docker Hub 的 `swebench` 命名空间拉取，不在本机构建。

## 官方评测命令（已对照文档与 SWE-bench 4.1.0 源码）

对照：

- [Evaluation](https://www.swebench.com/SWE-bench/guides/evaluation/)
- [Docker Setup](https://www.swebench.com/SWE-bench/guides/docker_setup/)
- [Harness reference](https://www.swebench.com/SWE-bench/reference/harness/)
- `swebench` **4.1.0** `swebench/harness/run_evaluation.py`

```bash
python -m swebench.harness.run_evaluation \
  --dataset_name princeton-nlp/SWE-bench_Verified \
  --split test \
  --predictions_path <predictions.jsonl> \
  --run_id <run_id> \
  --namespace swebench \
  --cache_level instance \
  --clean False \
  --force_rebuild False \
  --max_workers 1 \
  --instance_ids <id...>
```

仓库入口：`scripts/eval_swebench_mini.sh <predictions.jsonl> <run_id> <id...>`。

| 参数 | 取值 | 原因 |
| --- | --- | --- |
| `--dataset_name` | `princeton-nlp/SWE-bench_Verified` | 官方 Verified，不用第三方评测配置 |
| `--instance_ids` | Mini 子集 ID | 只评选定题 |
| `--namespace` | `swebench` | 拉取 Hub 预构建镜像；空命名空间才会本地构建。不能和 `--force_rebuild` 一起用 |
| `--cache_level` | `instance` | 保留实例镜像。默认 `env` 会在评测后删掉 `sweb.eval.*`，下次再拉 |
| `--clean` | `False` | 不清理高于缓存级别的镜像 |
| `--force_rebuild` | `False` | 有 namespace 时禁止重建 |

`swebench` 5.x 从 CLI 去掉了 `--namespace` / `--cache_level`，所以可选依赖钉在 **4.1.0**。换 `run_id` 才会重评同一题；同一 `run_id` 会复用旧结果，不管 patch 是否变了。

## 拉镜像

```bash
uv run python scripts/pull_swebench_images.py --limit 1 --log runs/pull-1.log
nohup uv run python scripts/pull_swebench_images.py --limit 10 --log runs/pull-10.log >/dev/null 2>&1 &
```

已存在的镜像会跳过。镜像名前缀可用 `--image-prefix` 或 `AGENT0_SWEBENCH_IMAGE_PREFIX`。

默认从 Docker Hub 的 `swebench` 拉。`--source epoch` 改为从
`ghcr.io/epoch-research/swe-bench.eval.x86_64.<instance_id>` 拉（instance_id 原样保留，不做 `__` → `_1776_`），再 `docker tag` 成下游使用的 `swebench/sweb.eval.x86_64.<id with __→_1776_>:latest`。agent / harness 不用改镜像名。

Epoch 镜像据其作者称与原版构建结果一致，但我们没有自行验证。

## 基线提示词差异

后续对比别家 agent 时，必须写明 agent0 多了下面两段，官方 `problem_statement` 本身没有它们。

任务文本（每题相同，写在 `problem_statement` 前面）：

```
The repository is at /testbed. Only modify non-test source files. After the fix, run the relevant tests, then call submit.
```

Headless system prompt 在固定 `SYSTEM_PROMPT` 后追加：

```
submit is available. You must call submit when the task is finished; the run does not end until you do.
```

交互模式没有 submit，也不加这段。任务文本仍只使用 `problem_statement`，不带 `test_patch` / `hints_text` / gold `patch`。

## 已知问题：实例镜像比 official `base_commit` 多一枚提交

在 `django__django-11790` 镜像（`swebench/sweb.eval.x86_64.django_1776_django-11790`）里：

```
# official Verified row: base_commit=b1d6b35e146aea83b171c1b921178bbaae2795ed
$ git rev-parse HEAD
84a9058f3ff86c9e7b27cc134460437fc9a4aac1

$ git log --all --oneline | head
84a9058f3f SWE-bench
b1d6b35e14 Fixed #30725 -- Fixed width of DateTimeField inputs in admin tabular inline.
faf4b988fe Fixed #30758 -- Made RangeFields use multiple hidden inputs for initial data.
733dbb21c7 Refs #30758 -- Added more tests for postgres.forms.ranges.
b9db423d3c Fixed #29376 -- Allowed hiding "Save and Add Another" button in admin.
44077985f5 Fixed #30775 -- Added admonition about missing imports to "Running tests" section in tutorial 5.
6c3dfba892 Fixed #30769 -- Fixed a crash when filtering against a subquery JSON/HStoreField annotation.
bd7e0f81f8 Added stub release notes for 1.11.25 and 2.1.13.
b8dff52f44 Fixed #29823 -- Doc'd limitation of DecimalField on SQLite.
4056558a1c Fixed typos in docs/ref/settings.txt.
```

`84a9058f3f SWE-bench` 是 `b1d6b35e14` 的子提交。agent 启动时记录的 `start_commit` 是镜像 HEAD，不是数据集的 `base_commit`。评测 harness 自己会按官方 base 处理；对比别家结果时要写明这一点。

补充（同一镜像）：

```
$ git tag | wc -l
8
# 1.0 1.1 1.2 1.2.1 1.3 1.4 1.7a1 1.7a2

$ git tag --contains HEAD
# 空：没有任何 tag 包含 HEAD（describe: 1.7a2-10282-g84a9058f3f）

$ git fsck --lost-found
error: refs/remotes/origin/HEAD: invalid sha1 pointer 0000000000000000000000000000000000000000
# dangling 对象 0；未写出 .git/lost-found
# origin/HEAD 是 `ref: refs/remotes/origin/main`，但 origin/main 不存在
```

## uv / swebench 依赖

`swebench` 钉在 `==4.1.0`（`pyproject.toml` 与 `uv.lock`）。`uv.lock` 只写 `https://pypi.org/simple`，不含清华/阿里等镜像站。组里有 `pyarrow`（约 51MB）、`numpy`、`pandas`，直连 PyPI 会卡很久。镜像只通过环境变量，不写进 `pyproject.toml` 或仓库里的 uv 配置：

```bash
export UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple
# 备选：https://mirrors.aliyun.com/pypi/simple/
uv sync --frozen --group swebench
```

干净目录验证（清华源，约 15s）：`UV_PROJECT_ENVIRONMENT=/tmp/agent0-swebench-clean UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple uv sync --frozen --group swebench`，装出 `swebench==4.1.0`。

## M4 设计备忘（来自 M6 真实运行）

`django__django-11790` 里模型几乎只用 bash 读写文件。M4 的状态记录要以 git 状态 / 文件哈希差异为准；读取要从 bash 命令里识别。现有遥测「重复读同一文件」只覆盖 `read` 工具。详见 `docs/milestones.md` M4。

## 本地缓存

- 题目行：`data/cache/swebench_verified/<id>.json`，或 `AGENT0_SWEBENCH_ROW_CACHE`
- 官方 harness 数据集：`HF_HOME`（评测脚本默认 `$REPO/.cache/huggingface`）
