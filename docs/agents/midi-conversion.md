# 显式请求后的完整 MIDI 转换

仅在用户明确说“也给我 MIDI”“把完整 PDF 转成 MIDI”等请求后读取本说明并开始音乐转写。用户只请求 PDF 时，不安装 Mido、不调用此模块、不展示 MIDI 配置或工具选择。理解请求由宿主 Agent 完成，不靠“包含 MIDI 字样”的关键词判断，例如“不要 MIDI”不是转换授权。

路线采用实测的 Agent 精确转写与可选 Mido。脚本不识谱、不调用付费模型、不自动理解反复，也不能证明调用者看过图。JSON 是 Agent 的内部工作记录，用户无需填写或逐小节纠错。

## Agent 操作

1. 完成并保留已审核 PDF，确认这份 PDF 的当前 hash。取得全部原截图、粗拼图和必要局部细节，按完整谱面空间顺序组织。原视频 PTS 与裁剪关系仍留在 PDF 任务记录中，不把派生图当原帧。
2. 在独立 MIDI 任务目录调用 `request_conversion()`，记录用户的原话与 Agent 已确认的请求意图。`requested_midi=False` 为严格无操作，即使传入不存在的文件也不创建任务或读取依赖。
3. 实际查看完整 PDF、粗拼图及所有原截图。Agent 按写下的小节 ID 转写全曲，各声部按记谱累计拍点。符梁、符尾、附点、三连音、休止和拍号决定时值；禁止把横坐标当拍点。鼓件依据本谱图例与谱位/符头对应，不猜作者自定义镲片。无法确认的内容保存为 `unresolved` 或 `mapping_unresolved`。
4. 对原谱逐小节完整校对。保留每个事件的声部、记谱依据、精确分数拍点与播放时长、GM 鼓件及明确 velocity。休止小节同样记录完整长度。`play_order` 写出反复、跳房、D.C./D.S. 等已确认结构展开后的全部小节 ID，包括每一次重放。每个写下小节必须出现，复杂记号未解决时停止可靠交付，不省略它们。
5. 明确统一播放政策。在 `policy` 写明未标力度、已标力度到 velocity 的映射、装饰音速度与前置时间、释放时长、重复后的力度行为及其他必要约定。不能把播放约定写成谱面事实。装饰音是实际 note-on/off 事件；临时缩短同鼓件前音的释放必须有明确政策，并保留原记谱时值。多个声部共享同一鼓件时先确认单个击打或两次演奏语义，不静默去重。
6. 调用 `submit_transcription()` 保存完整转写与实际审阅陈述。原截图、粗拼和 PDF 的所有路径都需列在 `viewed_sources`，所有写下小节列在 `reviewed_measures`，并保存具体公开音乐判断 `notes`。这只绑定调用者陈述，程序成功不等于实际视觉通过。
7. 只在无音乐/映射未决且完整审核后安装可选 Mido 并调用 `export_complete()`。它展开全部 `play_order`，输出每次回到反复起点对应的速度与拍号，导出后重新读取实际 MIDI 字节。核对击打、起拍、播放时长、鼓件、velocity、通道、tempo、拍号、note-on/off 配对和总长度。输出按实际标题命名，位于版本化子目录，旧 PDF 与历史 MIDI 均不覆盖。
8. 单独报告 PDF 与 MIDI 的结果。`midi_reviewed` 只证明当前完整转写通过调用者音乐审核陈述和实际字节回读。真实曲谱仍需实际逐小节音乐审阅证据；受控小谱例或软件测试不证明三条真实整曲首发。

可选依赖仅为 Mido 1.3.3，MIT，放到独立 uv 环境。完整 MIDI 工作流的安全文件名复用 PDF 基础模块，因此独立验证同时加载现有 `requirements.txt`，不新增 OMR 或音源依赖，不读取真实模型认证。

```sh
uv run --isolated --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt \
  --with mido==1.3.3 python -m unittest discover -s tests -p 'test_midi*.py' -v
```

Agent 内部调用示例，数值与路径必须来自本次实际材料。

```python
from midi_workflow import request_conversion, submit_transcription, export_complete, resume

request_conversion(midi_task, reviewed_pdf, all_originals_and_rough,
                   verbatim_user_request, requested_midi=True)
# Agent 此时实际查看完整 PDF 与 all_originals_and_rough，逐小节转写和校对。
submit_transcription(midi_task, complete_transcription, actual_music_review)
result = export_complete(midi_task)
```

## 内部转写字段

`title` 是实际谱名。`measures` 保留全曲写下的小节，`play_order` 是已审核的播放顺序。每个小节有唯一字符串 `id`、四分拍单位的 `beats`、`meter=[numerator, denominator]`、本小节生效的 `tempo_bpm`，以及全部声部的 `events`。每个事件含精确分数 `beat` 与 `duration`、GM note 35–81、velocity 1–127、非空 `voice` 和必要的 `notation` 审阅依据。`duration` 是明确政策下的播放释放时长，不会自动解析记谱符号。连音、连击、反复及声部合并都由 Agent 在音乐审核时解释；程序不替 Agent 选择。

480 PPQ 可精确表示常见二分细分与三连音。不能精确落在该网格的事件拒绝导出，不自动四舍五入。小节拍数须和拍号一致；拾音或自由拍号要明确处理，当前小节结构不支持拍数与拍号不一致的拾音。未知反复、不支持的时值或含糊装饰音保留未决，不声称通用全谱覆盖。

`unresolved` 和 `mapping_unresolved` 均为空才可在完整流程正常导出。底层 `midi_export.export_midi(experimental=True)` 的片段实验通道不能用于这个完整交付流程，`export_complete()` 不提供该参数。

## 失败、来源与续跑

`resume()` 重新核对 PDF、全部证据和 MIDI 输出的 SHA256；转写 hash 与实际审阅陈述、PDF/source hashes 一并绑定。来源或转写改变后拒绝沿用旧音乐审核，Agent 重新核查材料并提交。不要改 JSON 的 hash 来跳过审阅。

导出前拒绝 `exports` 符号链接，并检查 MIDI 目标仍在任务内。新版本目录必须不存在；外部目录、用户文件和历史导出不会被覆盖。

`needs_music_review` 保留未决与 PDF，不生成 MIDI。依赖缺失、事件冲突、实际 MIDI 回读失败等记录 `midi_failed`，PDF 保留。来源不变时再次调用 `export_complete()` 可重试，原失败文件不标为成功。导出写完后记录保存中断也可以在同一任务继续；每次生成新版本，恢复不重新要求用户提供 JSON 或逐小节修正。改变转写后提交会清除当前 MIDI 成功引用，历史文件仍保留。

KiLLKiSS 十五小节实测依旧有作者镲片图例未决。当前完整流程会拒绝把这条曲谱标为可靠 MIDI。技术路线已实测不等于作者映射已确认。小型完整实看验收见 `docs/experiments/issue-57-midi/README.md`；真实三视频的整曲验收另行记录。
