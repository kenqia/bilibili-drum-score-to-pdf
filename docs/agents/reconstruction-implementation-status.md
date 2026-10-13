# Issue #54 实施记录

本页记录本地实施状态。测试通过、实际视觉审阅和音乐校对分别记录；未完成的验收不能记作工单完成。

## 基线与工作区

- 重构前 Git 基线：`51aa468e1cab45010355100244a647ef3b8945e7`。
- 集成分支：`codex/issue-54-integration`。
- 任务图：#55 → #56 → #57 → #58 → #59。
- 初始可开始票据：#55。
- 初始工作区已有修改：`GLOSSARY.md`、`docs/agents/issue-tracker.md`，以及未跟踪的规格、ADR、研究、实验、`.scratch/` 和 `.archify/`。实施不覆盖这些材料，也不批量纳入提交。
- 基线状态与已有规格 hash 保存在 `/tmp/issue54-context/baseline.json`；票据只读快照保存在同目录。

## 当前实施状态

#55 的本地矢量 PDF 增量已合入集成提交 `402f3d1`。新的 `reconstruction.py` 复用媒体探测和实际 PTS 取帧，保存选行、粗拼与几何矢量来源，按完整行分页，并单独保存调用者的实际 PDF 审阅陈述。默认入口尚未切换。接口和现场证据见 [本地工作流](reconstruction-local.md)。

十五小节 MIDI 评估已合入 `b74aae3`，证据见 [实际 MIDI 比较](../experiments/issue-55-midi/README.md)。Agent 加 Mido 在声明的实验映射下，回读的 141 次击打、60 拍与独立原图基准一致。Audiveris 加 MuseScore 实际执行后仍少一小节，有限交换修正后仅 77/141 次击打的鼓件与起拍相符。两种高度的镲符号缺少作者图例，因此最终可靠后端未放行。

#55 明确允许记录无候选达到基准。这个评估结论不阻塞 #56 的 PDF 流程，但不能用于宣称 #57 的可靠音乐转换或 #58 的整曲 MIDI 验收通过。#56 已在基于 `b8ab5f6` 的独立 worktree 实施，尚未验收。

双轴审阅发现一项 P1：同名 PDF 阻塞重新选行和导出中断后的恢复。修复 `6a86cea` 已合入 `b8ab5f6`，每次导出使用独立版本目录，并保留真实谱名作为 PDF 文件名。旧产物及用户文件保留；当前 PDF 与矢量记录仍核验 hash。

新流程在分支中建立后，旧默认入口暂时保留。#58 的三视频完整 PDF、整曲 MIDI 和实际矢量兜底通过后，才执行 #59 的删除和正式切换。

## 验证与远端状态

- 基线完整 unittest：232 项，976.701 秒，231 项通过、1 项错误，退出码 1。错误发生在旧 `test_review_plan_above_compact_byte_limit_keeps_original_task_waiting` 构造视频时，ffmpeg 被 SIGKILL；错误不涉及新增模块。日志为 `/tmp/issue54-context/baseline-unittest.log`。
- 同项第一次复查仍被 SIGKILL，第二次串行复查 1 项通过、39.531 秒，日志为 `/tmp/issue54-context/baseline-review-serial.log`。执行期间曾观察到内存紧张，但未取得证明 SIGKILL 原因的系统记录。单项通过不把原完整回归改记为通过。
- 本地新工作流专项：修复后的 11 项通过，集成 `b8ab5f6` 上重新执行，3.088 秒。覆盖无效媒体、来源损坏、未决拒绝、失败恢复、用户文件保护、重复音乐与短末行分页。
- 实际视觉验收：KiLLKiSS 起始第 1–15 小节的小范围原图与一页矢量 PDF；`pdfimages -list` 无位图。尚未验收整曲、新生图或三视频。
- MIDI 可选专项：集成 `b8ab5f6` 上使用 Mido 1.3.3 重新执行 6 项通过。普通 PDF 依赖未增加 Mido。
- PDF worktree 的重复全回归未完成，保留日志及中止记录，不计为通过。集成最终完整回归尚未运行。
- 基线、审阅和小范围 PDF/MIDI 视觉证据副本保存在 `experiments/2026-10-13-issue54-local/`，`archive.json` 记录来源及复制后 hash。临时任务的原路径仍保留；副本不冒充新验收。

没有 push、PR、远端合并、Issue 修改或产品发布。完整模型成本未知，保持 `null`。软件增量和片段验收不代表 Issue #54 已完成。
