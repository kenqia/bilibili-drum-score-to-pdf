# 按疑点组织审阅

`review-plan` 提出五线几何、空间对应、候选裁剪和待检查区间，并给出原生 ROI 与局部补采请求。它始终返回 waiting，不接受决定，不生成 PDF，不改写观察包、接受历史或采样预算。默认 prepare/full 和所有既有视觉门禁保持原样。

```sh
uv run --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt python skills/bilibili-drum-score-to-pdf/scripts/convert.py --operation review-plan --task /absolute/task --output /absolute/new-plan
```

输出目录必须为空。`review-plan.json` 保存当前观察绑定、建议、分类疑点、实际 PTS 前后关系、必须审阅的原图范围、已有预算和下一步。`build-template.json` 是 `build-decision` 的输入模板；其中视觉审阅、完整性和覆盖确认均为 false，实际呈交清单为空。Agent 必须完成实际审阅后填写，不能把模板当作已确认决定。

`review-plan.json` 使用紧凑 JSON 保存全部字段。限额仍为 1 MiB，按实际 UTF-8 字节计算，包括末尾换行。多帧、多行的上下文和全部合理位移不因排版空白过大而丢弃；紧凑内容本身超限时继续返回 `sampling_budget`，保留任务和疑点。观察包、决定、请求与构建模板继续使用原来的缩进格式。

## 能力声明与原生证据

脚本不知道 Agent 是否能查看图像。默认 `image_access=unknown`，保留能力疑点。可通过 `--decision /absolute/capability.json` 声明能力，文件只含以下字段。

```json
{
  "schema_version": 1,
  "task_id": "当前任务 ID",
  "observation_sha256": "当前观察 hash",
  "observation_version": 1,
  "image_access": false
}
```

`true` 仅表示可以访问图像，不表示已经看图。没有访问能力时保持 waiting。实际图像呈交数、工具调用和模型成本仍从宿主计量取得，没有可信来源时保留 null。

每个疑点包含 `reason`、`risk`、有序 `context` 和必要原生矩形。上下文记录源图 hash、实际 PTS、time_base、timestamp 和保存路径；缩略图不能代替细小符号核查。脚本按以下原因分类。

- 遮挡或光标、没有干净完整观察、候选边界不明。
- 五线几何缺失、重叠不足、多个合理位移、无法解释的跳变、比例或横向布局变化。
- 标题、速度、拍号和行外区域尚未核查。
- 相邻采样间隙和导航预算留下的未决覆盖。

即使最大重叠的对应唯一，较少重叠但仍满足两条五线几何的位移也列为歧义。脚本不会据此自动放行。候选 clean 只说明检测器没有发现某类遮挡，不能证明任意遮挡不存在，也不建立空间身份。

`materialize-request-NNN.json` 使用现有 ROI 请求协议，可直接交给 `materialize`。只请求尚无完整原生细节覆盖的所选谱行或疑点区域，相同原帧与 bbox 去重，每份最多 128 个区域。当前原帧保留，不生成新拼图。没有可靠行框时请求原帧范围，避免编造裁剪边界。

物化会更新观察 hash。执行一份请求后重新运行 `review-plan`，再处理剩余疑点。不能把旧模板、旧补采请求或旧 ROI 请求重新绑定为新观察。重复相同 ROI 请求的缓存行为仍由 `materialize` 保证。

普通谱行仍要求实际查看当前协议规定的全部原帧，并取得所选单帧裁剪的完整原生细节。`review-plan` 帮助减少机械填写和重复展开，本轮不能把普通行的视觉门禁换成“只看疑点”。

## 局部补采与恢复

`supplement-request-NNN.json` 使用现有补采协议。每份范围不超过 30 秒，只提出一个尚未请求的范围内时刻，既有每次 8 帧上限保留。脚本按当前持久化 sampling 账本检查累计预算，包括之前失败或中断已扣除的额度。

预算不足时，疑点的 `supplement_available` 为 false，`supplement_blocked_by` 记录原因，不输出可执行请求。计划生成不会扣预算；实际补采才按既有规则预扣。一次请求的合法性不表示所有计划请求可以同时执行，应执行后重新规划。

补采后的实际 PTS 仍可能重复已有帧，既有补采操作会拒绝并保留已经发生的成本。新原帧改变接续关系，必须实际复查并构建绑定新 hash 的决定。`resume` 保留当前证据、未决状态和预算，计划不能把 failed/waiting 任务变成成功交付。

## 沿用已接受的实际判断

`build-decision` 可显式设置 `reuse_accepted_review=true`，以最新接受结构为基础，继续提供最新 `revision_of`、新 `decision_id` 和当前观察绑定。请求不能同时用新 `proposal` 替代接受基础。

这条路径只支持原帧序列完全不变的证据物化。脚本核对接受历史、归档观察 hash、源视频 hash、每帧的 hash/PTS/time_base/尺寸，以及之前声明实际呈交的每份图像记录。新增原帧、改变审阅前缀或改变旧呈交证据时拒绝沿用，需要明确复查新接续。

结构未改变的记录可以保留原有视觉判断。改变 bbox、ROI、所选帧、身份对应、原生证据引用或额外区域时，该记录的判断清空，必须由本次实际审阅重新确认。未改普通行无需重复填写全部判断。决定结构全部未改时，原有 visual_review/complete/依据可以沿用；调用方仍须明确确认 identity、coverage 和 outside 三项，任何未决项仍阻止提交。

旧呈交清单只在证据核对通过后沿用。新 ROI 不会被自动列为已看图；只有本次调用方明确填写的 `review.presented_images` 才会追加。`sources.json` 的 `reused_review` 记录接受决定 hash、归档观察 hash 和沿用字段路径，说明哪些判断来自历史。

这是 #47 初版之外新增的显式路径。未指定此 flag 时，原来清空判断并要求重新确认的行为继续保留。#50 的逐项审计需绑定新决定文件，不能因为复用了行判断就自动沿用旧审计。

## 标题与覆盖审计模板

lazy 计划额外输出 `score-audit-template.json`，使用 #50 的输入格式，不建立另一套审计协议。单段 ID 为 `score-000`，title、tempo、time_signature、outside_rows 各项都是 pending，首尾完整性为 false，相邻区间都是 pending。此文件不证明任何项不存在。

构建器现已支持 [整曲与行外区域审计](coverage-audit.md)。Agent 实际核查原生区域、打印选择和覆盖，再将该模板填入 `review.score_audit`。有标题或独立记谱区域时，须在 v4 proposal 的 extras 指定实际打印的单帧原生裁剪；标题不能继续从检测器框隐式导出。首尾与每个相邻区间的审计也需要对应原帧的完整原生证据。只有 `outside_rows_verified=true` 或一句文字依据仍不足以代替逐项审计。这个模板本身不提交、不放行，也不能证明未采样区间不存在隐藏换谱。

## 本地验证

```sh
uv run --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt python -m unittest discover -s tests -p test_agent_review.py -v
uv run --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt python -m unittest discover -s tests -p test_decision_builder.py -v
```

合成测试从 CLI 检查混合干净/遮挡片段、低重叠替代位移、尺度变化、五线缺失、原生 ROI、旧 hash 拒绝、保存决定导出重放、无图像能力、实际操作计量、持久预算和显式历史判断复用。没有调用真实模型或下载真实视频。完整回归和真实验收由集成阶段执行，自动接受门禁保持关闭。

2026-10-10，首次 RED 运行因 CLI 未识别 `review-plan` 失败；补上入口和疑点规划后通过。显式历史复用先因不受支持返回 failed，增加归档核验后通过。跨进程复用的四个 JSON 文件比较发现已接受结构的 set 遍历会改变键顺序，改用排序遍历后逐字节一致。

#50 集成前，本票 7 项专项通过，26.487 秒。干净 lazy 片段完成 ROI、构建、提交、导出和 PDF 字节重放；混合光标片段用于疑点分类与 waiting，不作为污染对应已经恢复的证明。旧 full 的显式复用单独核对修订历史、导出重放、新 ROI 未被自动呈交，以及新补采帧拒绝沿用旧接续。#47 的既有 9 项回归通过，35.005 秒。编译检查和 `git diff --check` 通过。

必需身份对应仍被光标污染时，当前内容门禁可能无法靠单张补采解除。该情形继续等待，没有协议改动或口头 override。lazy 正例必须通过绑定当前决定的逐项审计；本节不是完整真实视频验收记录。


2026-10-10，合入 #49/#50 门禁后，旧 lazy 正例缺少逐项审计，专项 RED 保持 waiting。测试改为通过公开 ROI 操作取得首尾和 gap 的完整原生证据，再提供显式 v4 title extra 与有效 `review.score_audit`，没有改动生产门禁。适配后 7 项专项通过，25.872 秒。干净 lazy 的三个打印行选择末帧真实裁剪，标题使用首帧显式区域，接受历史保存审计 hash；export/replay 的 PDF 字节一致，`hidden_content_proven_absent=false` 保留。删除审计后不能提交，混合光标片段即使声称全部确认仍 waiting，导出没有成功 PDF。full 历史复用单独保留其兼容范围。

同一门禁快照的 #47 既有 9 项兼容回归通过，25.074 秒。`git diff --check` 通过。本次适配只修改测试和本页文档，没有执行完整仓库回归、下载真实视频或调用真实模型。

## 最小链任务的短摘要

仅新任务的 `--minimum-evidence-chain` 开关启用这个输出。CLI 返回 `summary` 和详细 `review-plan.json` 的绝对路径，不再把原始数百条 issues 全部送回调用方；详细文件仍保存全部证据。摘要区分关键接续缺口、已有替代证据、重复几何候选和低价值诊断，列出每个关键区间的下一步。首尾、行外、所有原帧、全部区间和打印来源的实际审阅仍必需。

初始检测 proposal 没有建立身份，不能据此把重复候选当作漏行。Agent 已实际确认结构后，可将当前绑定的 build-decision 请求交给 `review-plan --decision`。计划会复用构建与几何、内容、覆盖门禁，保存 `bound-build/` 草稿，仍不接受决定。没有实际原生核查时，草稿和摘要保持等待，不自动填写 true。

定向补采只针对关键内容证据不足的区间；已有可靠替代的光标诊断不再重复补采，明确 conflict 先纠正对应或核查源内容。相邻缺口按不超过 30 秒的局部范围合并，单份最多 8 个新时间，去重并按当前账本模拟累计请求和帧预算。计划不扣预算，一份请求执行后改变观察绑定，必须重建其余请求。预算拒绝原因保留在摘要。
