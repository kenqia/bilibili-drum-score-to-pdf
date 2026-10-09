# 按需原生证据，实验入口

`prepare` 仍默认 `--evidence-mode full`。显式 `lazy` 只保存真实原帧和全局导航 comparison，检测候选保存为坐标元数据，不批量生成原生切片、谱行图或批次 comparison。批次元数据仍保留，`image_id` 指向全局 comparison。原生细节请求不改变空间身份或接受条件。

```sh
uv run --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt python skills/bilibili-drum-score-to-pdf/scripts/convert.py /absolute/video.mp4 --output /absolute/task --evidence-mode lazy
uv run --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt python skills/bilibili-drum-score-to-pdf/scripts/convert.py --operation materialize --task /absolute/task --decision /absolute/roi-request.json
```

ROI 请求严格包含以下字段。值从当前 `task.json`、`observation.json` 取得，不能用请求时间替代实际 PTS。

| 字段 | 值与约束 |
| --- | --- |
| `schema_version` | 整数 1 |
| `task_id`、`observation_sha256`、`observation_version` | 当前任务与观察版本绑定 |
| `source_sha256` | 当前原视频 hash |
| `request_id`、`reason` | 非空字符串，至多 2000 字符，说明当前疑点 |
| `regions` | 1 至 128 项，每项只含 `frame_id`、`frame_sha256`、`pts`、`time_base`、`bbox` |
| `bbox` | 原帧整数坐标 `[left, top, right, bottom]`，右下边界不包含在裁剪内，禁止越界或零面积 |

每份图像来自指定同一真实帧的 RGB 原裁剪，不缩放，不标注，不修复像素。证据记录保存源 hash、原帧 hash、实际 PTS、time_base、timestamp、bbox 和 `native_pixels` 映射，`scale=[1,1]`。请求使用已有原帧，不 seek、不补采；不会消耗采样请求数或增加原生帧预算。JSON 仍受既有 1 MiB 上限保护。

相同 `request_id` 和完整请求内容重复执行时，先核对当前任务、原视频和全部已发布图像，再返回已生成证据。观察版本和 hash 不改变。相同 ID 内容改变会拒绝。使用新 ID 请求相同原帧与 bbox 时复用已发布图像，记录新的证据更新版本。这个版本变化让新请求原因可追溯，不表示再次生成图像。

证据更新使用现有 `publication.json` 发布事务，同时更新 observation、task 和 sampling。旧观察保存到 `observation-vN.json`，请求保存到 `evidence-request-N.json`，观察中的 `evidence_updates` 保留请求内容、前版本 hash、图像引用和实际生成数量。中断发布由 `resume` 完成；发布前生成的图像保留，重试会逐像素核验后复用。新增路径禁止跟随符号链接。既有预算记录保持原值，包括先前失败补采已消耗的额度。

更新后任务进入 waiting/review，旧观察决定无法提交或导出。接受历史与已审前缀保留，已接受 hash 不重写。Agent 可以保留未改变普通谱行的 rows、observations、视觉判断与呈交图像，只审阅相关新增细节，然后提交协议 v5 封装的显式修订，`revision_of` 引用最新接受决定 ID，内部决定绑定新观察 hash。脚本重新验证来源、原生覆盖和几何；修订不会自动声称 Agent 看过新图像。未接受决定的任务使用现有 v2、v3 或 v4 提交流程。惰性候选只有元数据，不能直接作为 v1 候选细节引用。

`supplement` 继承任务 evidence mode，保留已发布 ROI 和证据更新记录；新原帧仍不批量切片。失败、中断和预算耗尽保持既有约定。新增帧可能插入已审时间范围，此时需要显式核查新的接续，不能把旧前缀当作已审新帧。

每次 `materialize` 操作计入性能账本，图像生成使用既有 `image_generation` 阶段。操作 metrics 给出本次 `generated_images`、`cache_hits` 和逐份 `generated_evidence` 来源记录，每完成一份就持久化。统一 report 的 `materialization` 汇总实际生成数、失败或中断操作已生成数及缓存复用数。未发布 ROI 保留为来源证据和失败成本，不能计入已接受图像。原有 `generated_images` 汇总仍是当前观察中已发布图像总数，二者分别报告。新增证据撤销当前交付确认。图像实际呈交仍由宿主事件提供，决定的 `presented_images` 不能替代计量。

本轮仅有合成软件验证。真实 URL 双跑、两份独立视觉判断、保存决定重放和完整宿主成本基线尚未验收；本入口不能作为默认快路径放行依据，也不能据此声称端到端耗时或总 Token 已降低。
