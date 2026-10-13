# 新版命令入口

`convert.py` 将 Agent 的操作请求转交给 `score_workflow.py`，不内嵌模型调用。省略 operation 使用 prepare。输出为 stdout JSON，成功调用退出 0，输入或来源验证失败退出 2。成功准备仍处于待审阅状态。

```sh
uv run --isolated --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt \
  python skills/bilibili-drum-score-to-pdf/scripts/convert.py video.mp4 --output /absolute/new-task
uv run --isolated --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt \
  python skills/bilibili-drum-score-to-pdf/scripts/convert.py --operation capture \
  --task /absolute/new-task --request /absolute/capture-request.json
```

第二个请求文件为 `{"seconds": 12.5}`。请求对象字段对应[工作流接口](reconstruction-workflow.md)中函数除 task 外的命名参数；例如 navigate 使用 seconds/width，present 使用 identifiers/notes，assemble 使用 title/regions/review。`--request` 文件最大 8 MiB。prepare 只接受 input、output 与 acquisition-timeout；resume 和 export 不需要请求文件。

| 操作 | 公共函数 |
| --- | --- |
| prepare / resume | prepare / load |
| navigate / capture / present / assemble | 同名函数 |
| redraw-inputs | redraw_inputs |
| begin-redraw / finish-redraw / fail-redraw | begin_redraw / finish_redraw / fail_redraw |
| review-redraw / reject-accepted-redraw | review_redraw / reject_accepted_redraw |
| export / review-pdf | export / review_pdf |
| midi-request / midi-submit | request_conversion / submit_transcription |
| midi-playable / midi-export / midi-resume | submit_playable_transcription / export_complete / resume |

MIDI 参数见[独立转换流程](midi-conversion.md)，仅在用户明确要求时读取。任务目录与 MIDI 任务目录分开。宿主生图调用在 begin-redraw 与 finish-redraw 之间由 Agent 实际执行。

公开 URL 使用匿名获取，支持分 P。失败写入只有获取诊断的 manifest.json 时可以在同目录重试或改用本地输入；新增用户文件后不再视为可重试空任务。原视频保存在相邻 `<task>-source-<id>` 目录，并通过 record.json 记录 hash。中断保留现有完整证据；不要删除来源目录，否则恢复会拒绝。

旧 task.json/observation.json 格式和旧操作不兼容。另建新版任务，保留历史文件。恢复已有新版任务时使用 resume，或重新 prepare 同一来源，不重复下载。回滚用先前 Git 提交的独立 checkout，转换使用新目录。
