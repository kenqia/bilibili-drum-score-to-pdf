# #63 自动来源检查记录

2026-10-14，`native-visible-ink/2` 与 `geometry-temporal/8` 通过统一 CLI 合成验证。完整带 Mido 回归为 122 项、100.064 秒，全部通过。命令见 [验证入口](../verification.md)，本机日志为 `/home/kenqia/issue61-context/ticket63-full-final.log`。`python -m compileall -q skills/bilibili-drum-score-to-pdf/scripts tests` 与 `git diff --check` 通过。

新增验证覆盖连续实际 PTS、18 秒短暂换页、非零起点解码、取消恢复、部分区间补采、首尾无谱、后续 A-B-A 重复音乐、固定上行与下行滚动、两像素小记号、高位四像素记号、标题自身变化、非零滚动中扩展裁剪的新记号、移动播放竖线、实际触边、白色和实心黑色遮挡、纯五线片段、无效及有效裁剪修订、冻结失效和宿主请求资格。单像素无法归类时，测试要求保留未决且不重新打印整个静止谱面。

## 新鲜真实来源

标准曲来源为 BV1rH4y1R7Rk-p1.mp4。独立任务在 `/home/kenqia/issue61-context/real63-native-v4-standard`。程序连续观察 8958 个原生帧，保存 26 个候选，实际末帧时间为 298.567 秒，视频时长 298.6 秒，逐帧解码累计 152.3659 秒。记录包含实际 PTS、时间基准、来源与截图 hash。它没有重放历史人工选行。

最终 `auto-freeze` 返回 `blocked`。当前材料包含一个标题块和十二条完整谱行。两处滚动观察中的上方墨迹消失由至少两条独立完整行、唯一非零垂直位移及后续没有新增墨迹共同定位，选行保留先前完整来源。部分五线只按相邻完整原生证据恢复，没有生成隐藏记号。

唯一剩余疑点为 capture-0013 与 capture-0014 之间的原生像素边界 `[1720,85,1721,86]`。静止布局其他行相同，但一个未匹配像素不能确定是记谱变化还是栅格差异。程序保存 `ambiguous_visible_ink_change`、两个来源和原生 ROI，拒绝生图输入。再次运行复用当前材料，未生成新的模型请求。

Root 实际查看全部粗拼，确认标题、速度、署名、首尾终止线和十二条谱行的顺序，未见整屏重复打印。开镲、重音、括号符头、装饰音、行下符杆、56 行末叉形记号和 72 行上方长渐强或渐弱线保留。标题边缘较紧，后续排版需检查。这次查看没有消除单像素疑点，不等于逐符号音乐校对或完整交付批准。

本机证据如下：

- `/home/kenqia/issue61-context/real63-native-v8-final-freeze.json` 保存最终公开操作结果和材料引用。
- `/home/kenqia/issue61-context/real63-native-v8-evidence/summary.json` 保存来源、实际 PTS、ROI、逐帧观察、选行数量和未决；同目录保存两张原生 ROI。
- `/home/kenqia/issue61-context/real63-root-rough-review.md` 保存 Root 实际粗拼查看。
- `/home/kenqia/issue61-context/nonzero-seek-diagnosis.json` 保存非零区间零帧根因及恢复验证。
- `/home/kenqia/issue61-context/ink-mask-equivalence.json` 保存 OpenCV 墨迹实现与原实现的完整 RGB 穷举等价结果。

没有新的宿主生图、最终 PDF 审阅或 MIDI 输出。模型成本为 `null`，受控宿主请求只证明接口与冻结绑定。原生来源疑点需按[实际来源审阅与 assemble](../agents/reconstruction-workflow.md)解决；裁剪与补采操作不能替代对原谱位置的新视觉判断。
