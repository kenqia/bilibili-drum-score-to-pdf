# 宿主实际计量与基准汇总

`host_usage.py` 从授权宿主记录提取计量，或接收调用方提供的受控事件。它不调用模型，也不改变 prepare、身份检查、视觉决定或 PDF 导出。实际 Token 和已观察 Token 分开保存。找到 usage 文件只说明计量来源可用，不能证明完整视频基线已经完成。

## 从当前 Codex Desktop 采集

Agent 为每次视频任务记录 invocation ID、开始与结束时间，以及实际参与的 thread ID。默认读取 `CODEX_HOME` 和 `CODEX_THREAD_ID`；必要时按顺序检查 WSL home 与自动发现的 Windows 用户目录。先读取会话首行元数据，核对 ID、cwd、`Codex Desktop` 来源及父子关系。相同 inode 只读一次，找到优先来源后不合并其他目录。当前 root turn 可从该根会话的安全元数据自动发现，历史调用可显式指定 `--root-turn`。

```sh
uv run --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt python skills/bilibili-drum-score-to-pdf/scripts/host_usage.py collect \
  --task /absolute/task --invocation song-review-1 \
  --thread-id ACTUAL_REVIEW_THREAD_ID \
  --start 1791537000 --end 1791537600 --mode review_only \
  --output /absolute/new-usage-events.json
```

时间支持 Unix 秒与带时区的 ISO 8601。`--thread-id` 可重复，只有经父子元数据核对且显式列出的线程参与采集。根线程的开发工作不会因同属会话自动计入审阅。`--cwd` 默认当前工作目录，`--codex-home` 和 `--root-thread` 提供明确的历史来源覆盖。采集不修改任务，只写新的脱敏事件文件，已有输出拒绝覆盖。

采集器只输出稳定计量 ID、时间、Token 字段和工具名称，不输出会话正文、推理、工具参数或结果。它不读认证、配置或 SQLite，不下载或安装 SDK。`token_usage_record.usage` 是逐响应实际量，`token_count` 镜像及累计计数不进入总量。模型可见标识以任务决定或受控基准元数据保存，未知精确模型版本保留 `unknown`。

当前 Desktop JSONL 不提供完整响应开始和失败调用账本，也不能可靠还原 exec 内部所有 MCP 调用与实际图像呈交。采集结果的四项 coverage 均为 false。不存在记录不能解释为零消耗。采集窗口结束时还在运行的响应可能尚未落盘，结束后可重复采集更长窗口并幂等导入。最终报告仍保留缺失原因。

## 导入受控事件

```sh
uv run --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt python skills/bilibili-drum-score-to-pdf/scripts/host_usage.py import --task /absolute/task --events /absolute/usage-events.json
uv run --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt skills/bilibili-drum-score-to-pdf/scripts/convert.py --operation report --task /absolute/task
```

事件文件绑定 task ID、performance lifecycle ID、invocation、线程 allowlist 与时间范围，保存为独立 `host-usage.json`。同事件重新导入不重复记账，改写已有事件或用另一个事件 ID 重复计量同一响应、同一工具调用会拒绝。真实重试使用新的 response/call ID 并累计，失败调用保留 usage，缺失 usage 用 null。导入旧快照不会删除新快照已有事件。

最小完整格式如下。调用方的 complete 声明须有自身完整调用与终止账本支持，不能从本项目采集器的 partial 快照升级而来。

```json
{
  "schema_version": 1,
  "lifecycle_id": "ACTUAL_LIFECYCLE_ID",
  "task_id": "ACTUAL_TASK_ID",
  "source": {"kind": "host", "id": "caller-1"},
  "scope": {
    "invocation_id": "song-1", "root_thread_id": "root", "root_turn_id": "turn",
    "thread_ids": ["root"], "started_at": 1791537000, "ended_at": 1791537600, "mode": "review"
  },
  "coverage": {
    "lifecycle_complete": false, "model_calls_complete": false,
    "tools_complete": false, "images_complete": false,
    "expected_response_ids": ["response-1"], "missing_reasons": ["Caller response coverage unavailable"]
  },
  "events": [{
    "kind": "model_call", "event_id": "usage-1", "thread_id": "root", "timestamp": 1791537100,
    "response_id": "response-1", "status": "complete",
    "usage": {"input_tokens": 100, "output_tokens": 10, "total_tokens": 110, "cached_input_tokens": 64, "reasoning_output_tokens": 4}
  }]
}
```

source.kind 只允许 `host`、`codex_desktop_jsonl`、`controlled_fixture`。mode 为 `review`、`review_only` 或 `replay`。模型与工具 status 为 `complete`、`failed`、`cancelled` 或 `unknown`。未知字段拒绝，不会暗中加入总量。

Token 总量等于 input + output。可选字段为 cached_input、cache_write_input、reasoning_output、text_input 和 image_input 的 `_tokens` 字段，它们是总量的拆分。缓存拆分不得超过 input，推理不得超过 output。只有全部响应提供同一个拆分时，完整总计才有该字段的值；部分来源提供时另列已观察拆分，完整值为 null。总实际 Token 要求生命周期范围关闭、覆盖提交到终止或首次交付、调用方确认全部模型调用且预期响应均有 usage。`review_only` 始终不能宣称完整生命周期。受控调用方明确证实完整范围内没有模型调用时，input/output/total 可为零；不可观测来源始终为 null。

工具事件采用以下字段，外层模型调用与内部 seek、解码、shell 执行分别统计，不能混加。

```json
{"kind":"host_tool_call","event_id":"tool-1","thread_id":"root","timestamp":1791537100,"call_id":"call-1","tool_name":"view_image","status":"complete"}
```

实际图像呈交事件必须在图像送入模型时记录，每次呈交有独立 event ID。生成 PNG 或运行 view_image 成功不能替代呈交事件。

```json
{"kind":"image_presented","event_id":"delivery-1","thread_id":"root","timestamp":1791537100,"call_id":"call-1","image_id":"frame-000","image_source":"observation","width":640,"height":360,"panel_count":1,"source_pixels":2073600}
```

observation 图像 ID 必须属于当前观察包，source_pixels 与保存图像的实际尺寸相符。delivery、diagnostic 用于 PDF 页或额外诊断图；它们不满足观察证据要求，未知源像素为 null，已提供源像素也只属调用方声明。决策 presented_images 仅和 observation 呈交 ID 集合核对，额外交付图不造成错误匹配。报告同时列呈交次数、唯一图像、重复次数、实际呈交像素、面板数和经核对的观察源像素。实际呈交尺寸不等于模型内部编码尺寸，也不证明模型理解每个面板。

## 多次运行汇总

`aggregate --runs /absolute/runs.json` 输出分组 P50/P90、状态率和完整性。输入为 `{"schema_version":1,"runs":[...]}`，每项提供 `run_id`、`sample_id`、`code_version`、`entry`、`mode`、`input_sha256`、`environment_id`、`model_id`、`model_version`、`measurement_source`、`timeout_seconds` 和统一 report 的 `performance`。entry 为 local/url；同样本 hash 必须一致，重复 run ID 内容一致时只统计一次，冲突或复用 lifecycle ID 拒绝。

报告按上述运行条件分组。成功且墙钟有效的可交付任务计算 nearest-rank，P50/P90 的秩为 ceil(q × N)。等待、失败、取消、超时均保留已发生时间，所有状态率使用全部提交任务作分母。成功交付样本小于十次时标记小样本局限，P90 可能就是最大值。完整实际 Token 只在分组全部任务有完整值时累计，未知不作为零；观察到的实际量另报。

固定决定重放、review_only 和 controlled_fixture 单列，不能作为真实 Agent 性能放行依据。`real_baseline_eligible` 只检查真实来源、完整模型/工具/图像覆盖及完整 review 范围，不检查曲谱质量、样本数量或配对降幅。真实基线仍须冻结至少三类视频、入口、hash、时限、环境与重复次数，完成标准 URL 双跑及各自独立视觉、来源与 PDF 验收。

#45 软件边界可通过合成 CLI 与受控事件验证。当前 Desktop 来源无法证明全部失败调用和图像呈交覆盖；新鲜多视频完整基线及实际总 Token 降低仍未验收。开发会话成本、历史 prepare 时间和固定决定重放不能填补这些缺口。
