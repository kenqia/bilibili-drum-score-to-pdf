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
| stage / layout | stage / layout，阶段推进与打印参数 |
| overview / resample / auto-freeze / revise-crop | 同名函数（横线转下划线） |
| navigate / capture / present / assemble | 同名函数 |
| promote | promote，参数 identifier 为导航候选 ID |
| cache-report / cache-limits | cache_report / cache_limits |
| redraw-inputs / generation-materials | redraw_inputs / generation_materials |
| begin-redraw / finish-redraw / fail-redraw | begin_redraw / finish_redraw / fail_redraw |
| review-redraw / reject-accepted-redraw | review_redraw / reject_accepted_redraw |
| export / review-pdf | export / review_pdf |
| midi-request / midi-submit | request_conversion / submit_transcription |
| midi-playable / midi-export / midi-resume | submit_playable_transcription / export_complete / resume |

MIDI 参数见[独立转换流程](midi-conversion.md)，仅在用户明确要求时读取。任务目录与 MIDI 任务目录分开。宿主生图调用在 begin-redraw 与 finish-redraw 之间由 Agent 实际执行。

公开 URL 使用匿名获取，支持分 P。失败写入只有获取诊断的 manifest.json 时可以在同目录重试或改用本地输入；新增用户文件后不再视为可重试空任务。原视频保存在相邻 `<task>-source-<id>` 目录，并通过 record.json 记录 hash。中断保留现有完整证据；不要删除来源目录，否则恢复会拒绝。

旧 task.json/observation.json 格式和旧操作不兼容。另建新版任务，保留历史文件。恢复已有新版任务时使用 resume，或重新 prepare 同一来源，不重复下载。回滚用先前 Git 提交的独立 checkout，转换使用新目录。

## 原生缓存与生图组

导航保留原生候选及低清展示图。使用 promote 并传入导航 ID，将有效候选直接复制为来源截图；capture 使用时间参数，复用相同缓存。改变 navigate 的 width 不重新解码有效原生帧。任务恢复验证视频 hash，候选缺失或损坏按未命中处理，来源截图损坏仍阻止任务继续。

cache-limits 接受正整数 max_entries 和 max_bytes，默认 64 个候选及 256 MiB，按最近使用顺序淘汰候选。来源截图独立保存在 captures 中。cache-report 输出 hits、misses、promotions、evictions、actual_decodes、duplicate_decodes、容量及原因记录，每个计数附 definitions。实际成功原生读取计为 actual_decodes；返回以前已解码的来源 hash、PTS 和 time_base 计为 duplicate_decodes。seek_count 和 decoded_reported_frames 保留真实解码器计数。

默认 redraw-inputs 按连续完整谱行分组，每组最多 8 个 system，标题随首组保留。分组同时检查 8000 万像素预算，以及拟合 4096 像素长边后至少 4 像素的五线间距。这些是当前实现的资源与细节保护值，不是模型准确率承诺。单行已经低于细节阈值时保留完整原行，由实际输出审阅决定是否转矢量。显式 groups 保留现有公共接口和完整覆盖检查。

生图组不参考 A4 分页。generation-materials 仅在全部组 accepted 或 vector 后返回按原谱排序的完整行材料。imagegen 行包含生成图片引用、crop_bbox 和来源映射；vector 行提供原裁剪引用，method 为 contour_trace_with_staff_repair、music_recognition 为 false。当前导出使用相同边界与来源比例。

begin-redraw 在调用前保存 request、输入 hash、修正次数及未知 cost=null。calling 状态不可再次主生成；先用同一 request 回填已有结果。确认无法恢复时调用 fail-redraw，outcome 可以是 failed、unavailable 或 unknown，默认 failed。结果未知不能自动重新调用。实际查看输出后才提交 review-redraw，拒绝初次输出可修正一次，恢复不退还额度，第二次拒绝转矢量。受控测试回执不证明实际模型执行或音乐审阅。

## 自动来源检查

准备任务后可运行 `overview`、`resample`、`auto-freeze` 和 `revise-crop`。请求字段、冻结资格及检查限制见[程序检查与粗拼冻结](automatic-source-checks.md)。

## 阶段入口与恢复

准备后使用 `stage` 自动推进至宿主调用或实际审阅；局部来源版本、输入额度恢复、打印布局和全部页面预览见[阶段入口、局部恢复与打印布局](stage-recovery-layout.md)。`layout` 修改边距、最小行距和目标页数，复用已接受生成结果；最终审阅绑定当前 PDF hash。程序检查与实际看图分别记录。
