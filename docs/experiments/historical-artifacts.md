# 已移出当前树的历史材料

2026-10-23，按用户确认移除 48 份单曲实验、MIDI 中间产物、旧发布记录和设计访谈，共 1,917,443 字节。源码、测试、部署文件和 README 展示素材保留。

以下链接固定到清理前的提交 `265231e9e05c77329a5fa5b128b761c674f6f1b9`，可查看原始文件。历史命令和绝对路径不保证现在可运行，不作为当前产品能力或新输入验收。

| 材料 | 文件数 | 保留的结论与边界 |
| --- | ---: | --- |
| [KiLLKiSS 单曲实验](https://github.com/kenqia/bilibili-drum-score-to-pdf/tree/265231e9e05c77329a5fa5b128b761c674f6f1b9/experiments/2026-10-13-issue58-recovered/killkiss) | 13 | 脚本保存当时 Agent 已看图的选行和修复决定，不是通用算法。保留被替代产物、实际 PTS、来源 hash 和 55 项音乐未决；严格 MIDI 导出曾拒绝，不能称为可靠整曲转写。 |
| [十五小节 MIDI/OMR 对比](https://github.com/kenqia/bilibili-drum-score-to-pdf/tree/265231e9e05c77329a5fa5b128b761c674f6f1b9/docs/experiments/issue-55-midi) | 15 | Agent/Mido 在声明的播放约定下匹配 141 次击打；Audiveris/MuseScore 未达基准，作者鼓件映射未确认。含失败日志、MXL、ZIP 和候选 MIDI。 |
| [自建三小节验证](https://github.com/kenqia/bilibili-drum-score-to-pdf/tree/265231e9e05c77329a5fa5b128b761c674f6f1b9/docs/experiments/issue-57-midi) | 10 | 26 次击打、18 拍的受控谱例导出与回读通过，不能推导为真实视频整曲验收。 |
| [三首近似播放 MIDI](https://github.com/kenqia/bilibili-drum-score-to-pdf/tree/265231e9e05c77329a5fa5b128b761c674f6f1b9/docs/experiments/issue-58-playable-midi) | 5 | 用户放宽门槛后导出并回读，始终 `reliable=false`。映射、节奏和释放调整保留在 summary，未进行听感验收。 |
| [旧发布验收](https://github.com/kenqia/bilibili-drum-score-to-pdf/blob/265231e9e05c77329a5fa5b128b761c674f6f1b9/docs/release-test-2026-10-12.md)及[批次数据](https://github.com/kenqia/bilibili-drum-score-to-pdf/blob/265231e9e05c77329a5fa5b128b761c674f6f1b9/docs/release-data-2026-10-12.json) | 2 | 十次尝试中交付一份 PDF、八项 waiting、一项超时，当时首发门槛未通过。 |
| [2026-10-20 设计访谈](https://github.com/kenqia/bilibili-drum-score-to-pdf/tree/265231e9e05c77329a5fa5b128b761c674f6f1b9/docs/research) | 3 | 长截图、原图直排和连续条带分页的需求与取舍，当前产品边界以 ADR 0007 和各产品协议为准。 |

保留在其他历史 JSON 中的路径表示当时证据位置，不会因本次清理自动迁移任务或更新 hash。原始来源、实际 PTS、失败记录与未知成本继续按原记录解释。当前程序与网站不提供 MIDI，Skill 的当前公开入口也不提供旧 MIDI 子命令。
