# KiLLKiSS 十五小节 MIDI 候选实测

2026-10-13，两条路线均实际执行。Agent 转写加 Mido 在明确的谱位到 GM 播放约定下，与原图基准逐事件一致。Audiveris 加 MuseScore 未达到基准。作者的镲片映射仍未确认，因此本试验不交付可靠 MIDI，也不证明整曲首发通过。

建议后续继续使用 Agent 精确转写加 Mido 的技术路线。Mido 已验证写入和回读，不能替代识谱、作者图例确认或整曲校对。最终后端放行状态为未通过。

## 独立基准与候选

原图基准是 `source-benchmark.json`，来自已有实验的九个真实谱行裁剪。每个小节保留谱行 SHA256、原帧 SHA256、实际 PTS、time_base 和 bbox。Agent 实际查看这些裁剪与首帧标题速度，并查看 23、27、67、75、113、135 的放大图。根 Agent 另从扩大原裁剪发现第 75 小节初始 detail 裁剪漏了左端开放踩镲，基准修正后保留该击打；67 的三连音也经二次原图复核。

候选是另一 Agent 独立从 `KiLLKiSS-vector-compact.pdf` 渲染和查看三页及九行后完成的转写。该 Agent 没有读取原图基准。完整原文见 `independent-pdf-review.md`。`agent-candidate.json` 从该独立文字逐项录入，未从基准复制事件。最终比较确认十五小节的击打、谱位、起拍、记谱时值、三连音、装饰音及短末行一致。隐含声部空白与印刷休止分开说明，空白不是新增休止符。

两份转写都覆盖 1、2、10、11、23、27、32、67、75、110、111、112、113、134、135。每小节四拍，总计 60 拍。10 和 11 是带数字 2 的多小节休止，每小节四拍，均无击打。

## 播放约定与未决项

拍点来自符梁、符尾、休止、附点、三连音和声部累计，不来自图像横坐标。JSON 中拍和时值用精确分数表示。

本次实验采用 [Audiveris 官方默认鼓件表](https://audiveris.github.io/audiveris/_pages/guides/specific/drums/)的五线谱位与符头约定。MIDI 用零起算通道 9。底鼓 36，军鼓 38，下位 tom 43，上位 tom 48，中间 tom 47，开放踩镲 46，下位 crossed oval 49，上位 crossed oval 57。该官方文档明确没有统一鼓谱映射，作者可以采用不同约定。独立 PDF 审阅者将下位 crossed oval 读为可能的 ride，与官方默认 crash1 有差异，不能把实验采用 49 当作作者意图已确认。匿名源视频简介没有图例或工程链接，仍保留未决。

原谱片段没有标力度，主音统一 velocity 96。三个斜线装饰音统一 velocity 64，时长为 1/16 个四分拍，放在主音前 1/16 拍。本例主音均不在小节首拍，因此不跨片段起点。该时间是播放约定，谱面没有记载这些数值。第 134 小节的两点是 staccato，记谱时值仍为八分，播放时长取其一半。其他音保留记谱时长，不补录音手感或音色。

`experimental-agent-excerpts.mid` 明确为代表性片段试验。其作者映射未决，所以 `reliable` 为 false。低层导出器只检查输入事件和 MIDI 技术约束，不认证源图、作者映射或音乐可靠性。正常可靠交付流程必须将所有音乐未决项放入 `unresolved`，它会拒绝写入。实验数据的 `author_mapping_unresolved` 保留采用约定后的作者事实疑点。正常导出也拒绝这个字段中的未决项；仅调用方显式传 `experimental=True` 时允许写入采用声明约定的试验文件。这个参数不放行其他音乐未决，也不替代逐小节审阅。

## 实际文件结果

完整机器可读结果见 `actual-comparison.json`，保留每个 MIDI 的实际速度、拍号、通道、note-on/off 配对、事件与总 tick。

| 检查 | Agent 加 Mido | Audiveris 加 MuseScore |
| --- | --- | --- |
| 原图基准击打数 | 141 | 141 |
| 实际十五小节候选击打数 | 141 | 108，另缺第 11 小节 |
| 速度 | 200 BPM | 原始输出 120 BPM，交换修正后 200 BPM |
| 总拍数 | 60 | 原始 OMR 少一小节，单片段还有超拍或缩短 |
| 鼓通道 | 9 | 9 |
| 与基准完全一致 | 实验约定下 15/15，141/141 事件 | 未通过 |
| note-on/off 配对 | 全部通过 | 生成的 14 个单小节文件均能配对 |
| 可靠作者鼓件 | 未通过 | 未通过 |

Mido 文件在 480 PPQ 下结束于 tick 28800，tempo 为 300000 微秒。包含三个装饰音和 8 分三连音的精确分数拍点；两小节休止没有击打，但保留各自 1920 tick。末小节完整四拍。实际字节回读后与独立原图事件比较，遗漏和新增均为零，鼓件、拍点、播放时长、velocity 及通道逐项一致。专项回归同时保留这些检查。

Audiveris 5.11.0 对完整三页矢量 PDF 真正执行 batch transcribe 和 MusicXML export，导出 134 个 measure，原谱为 135。首小节被标为 implicit，实际错误为遗漏一个四分休止并把最后两个十六分读成八分，导出后仅 7/2 拍；不能解释成合法拾音小节。原谱数字 2 的多小节休止被读成 1，造成一个小节丢失。日志另记录多处声部超拍。

MuseScore 3.2.3 真正导出完整候选 MIDI 和 14 个单小节 MIDI。单小节从原始 MusicXML 按谱面顺序提取，仅继承必要 attributes 和 part-list，不改音符；第 11 小节根本不存在，没有为它伪造 MIDI。原始交换的 midi-unpitched 少了 MusicXML 一起算转换，实际底鼓成 35、军鼓成 37 等；这由实际 MIDI 回读确认。

另实际做了一次有限交换修正，所有 midi-unpitched 加 1 并加入 tempo 200，未手工改任何识别音符。参考 [MusicXML midi-unpitched 定义](https://www.w3.org/2021/06/musicxml40/musicxml-reference/elements/midi-unpitched/)。修正后只有 77/141 次击打的起拍与鼓件相符；该数字不包括时长与力度通过。识别仍遗漏或错时 64 次，并出现错误或错时的新事件。第 75 小节只剩 5 次击打、13/4 拍，三个装饰音没有正确输出。第 27 小节 9/2 拍，第 110、113 小节 5 拍。静默第 10 小节的 MIDI 仅留 1 tick，并未保留四拍。原始默认力度为 80，常见音符释放比 MusicXML 时值短 1 tick，这些都保留在原始数据中，没有归一化后宣布成功。未继续重写原始 OMR 全部音符，因为那会变成新的人工转写路线，无法证明这条识别路线正确。

## 隔离依赖与验证

所有候选工具位于 `/tmp/issue54-midi-tools`。用 `uv venv` 安装 Mido 1.3.3，MIT；Pillow 12.3.0、ReportLab 5.0.1 仅用于查看实验裁剪，不加入产品 requirements。Audiveris 5.11.0 官方 Ubuntu 22.04 deb 解包，AGPL-3.0。MuseScore 3.2.3+dfsg2-11 的 Ubuntu deb 解包，包 copyright 标 GPL-2 with Font exception；缺失的 Qt、PortAudio、PortMidi、Poppler 动态库也仅 apt download 后解包到该目录。包有各自许可证，没有复制第三方工具进项目。

未安装系统包，未读取真实认证、模型设置或密钥。Java user.home 和 XDG 状态目录指定到隔离目录。没有音源下载或听感验收，输出正确性依据实际事件。普通 PDF 用户无需安装这些依赖。模型成本未知，记录为 null。

实际 OMR 命令如下，源码输入位于现有实验中。

```sh
JAVA_TOOL_OPTIONS=-Duser.home=/tmp/issue54-midi-tools/state \
XDG_CONFIG_HOME=/tmp/issue54-midi-tools/state/config \
XDG_DATA_HOME=/tmp/issue54-midi-tools/state/data \
/tmp/issue54-midi-tools/audiveris/opt/audiveris/bin/Audiveris \
  -batch -transcribe -export \
  -constant org.audiveris.omr.sheet.ProcessingSwitches.drumNotation=true \
  -constant org.audiveris.omr.sheet.ProcessingSwitches.oneLineStaves=true \
  -output /tmp/issue54-midi-results/audiveris \
  /home/kenqia/my_folder/bilibili-drum-score-to-pdf/experiments/2026-10-13-BV15crrYUEPA/KiLLKiSS-vector-compact.pdf

LD_LIBRARY_PATH=/tmp/issue54-midi-tools/musescore/usr/lib/x86_64-linux-gnu \
QT_QPA_PLATFORM=offscreen \
XDG_CONFIG_HOME=/tmp/issue54-midi-tools/state/config \
XDG_DATA_HOME=/tmp/issue54-midi-tools/state/data \
/tmp/issue54-midi-tools/musescore/usr/bin/musescore3 \
  -o /tmp/issue54-midi-results/audiveris/KiLLKiSS-candidate.mid \
  /tmp/issue54-midi-results/audiveris/KiLLKiSS-vector-compact.mxl
```

`omr-attempt` 保存实际 MXL、MIDI、`measure-attempts.zip` 中的原始与修正单小节 MusicXML/MIDI，以及本次工具产生的非敏感识谱日志。`extract_omr_measures.py` 与 `correct_omr_exchange.py` 保存本次提取和有限交换修正代码。没有保存工具安装包、完整视频或音频。

复跑 Mido 专项，不需要 Audiveris 或 MuseScore。

```sh
uv run --with mido==1.3.3 python -m unittest discover -s tests -p test_midi_export.py -v
```

本次隔离环境实跑六项全部通过，包括独立十五小节回读、未决拒绝覆盖、同鼓件重叠拒绝、布尔力度拒绝、作者映射未决拒绝普通导出和精确时间/静默保留。未另跑完整旧回归，主 Agent 串行处理仓库回归。

## 后续整曲边界

`midi_export.py` 可复用精确事件写入、原子替换和实际 MIDI 回读。它目前只导出恒定速度的 4/4 片段，不自动解释 MusicXML、反复、拍号变化、速度变化或装饰音。调用方先展开并校对音乐语义，明确播放约定，再传入实际拍点和时长。整曲至少仍需要作者映射确认、全部小节的独立校对及完整导出回读，不能从这里的 15/15 推导整曲可靠。
