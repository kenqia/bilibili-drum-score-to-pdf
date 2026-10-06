# 聊天回答、补图与重放

用户在聊天中回答，Codex 负责生成本地 JSON 答案文件。先展示 `issues` 的编号、问题、截图、源时间和相邻参考，再确认用户表达对应哪一个 `choices`；不能把含糊回复或等待时间当作确认。

答案文件的键为疑点编号，值为处理对象。只写下表字段，额外字段不会被接受。

| action | 额外字段 | 用户明确确认的含义 |
| --- | --- | --- |
| confirm_join | 无 | 无重叠的两个窗口直接连续，当前窗口全部谱行接在此前内容之后 |
| confirm_overlap | overlap | 重叠谱行数，必须是该疑点的 overlap_candidates 中一个整数 |
| confirm_repeat | 无 | 当前窗口是再次演奏的段落，完整保留本次出现 |
| confirm_hold | 无 | 当前窗口是同一处停留画面，不新增段落 |
| supplement | image | 用户提供的本地完整单行谱面图，使用绝对路径 |
| accept_missing | 无 | 接受无法恢复的内容，PDF 在对应位置显示缺失标记 |

例如用户明确确认无重叠窗口直接衔接，Codex 写入实际返回的编号：

```json
{"no_overlap-0003-00002000": {"action": "confirm_join"}}
```

再运行 `uv run /absolute/path/to/bilibili-drum-score-to-pdf/scripts/convert.py --resume /absolute/path/to/result --answers /absolute/path/to/answers.json`。没有新回答时只用 `--resume`，返回已有进度。`--resume` 不能同时指定新输入或 `--output`。

`action` 必须由当前疑点提供。重叠、运动或重复顺序有歧义时，单张补图不能决定整段顺序；使用明确的确认选项，或由用户明确接受缺失。未知编号、无效 JSON、缺少字段或不适用选择返回 `answer_error`，不覆盖已确认进度。

补图必须包含可观察的完整单行五线、上下符杆边缘和必要标记，源像素和五线间距须足够。不能从文字音符、听音结果或 MusicXML 补画谱面。像素不足、不完整、含多行或仍有光标遮挡的补图不能解决疑点。原 RGB 图和只转灰度的打印图都保留；已采纳补图记录文件指纹，不用后来的视频候选替换它。

接受缺失后，PDF 在原谱对应位置显示 `MISSING CONTENT` 并附限制说明，manifest 保存 `gaps`、`limitations` 和 `complete=false`。它可以交付供用户核查，但不是完整还原通过。

恢复会核查原视频、manifest、state 和引用证据的指纹，再从原视频重放到末尾或下一个未确认问题。只把已保存前缀排版不能证明整曲覆盖。旧证据保留在任务目录，新重放证据进入新的 `replay-*` 目录；同一个有效答案重复执行不会新增重复谱行。原视频或状态变更返回 `invalid_progress`，保留原目录，请用户核查而非覆盖。

JSON 文件通过原子替换保存，整个目录不是数据库事务。中断若造成文件间不一致，应报告未能恢复，不声称自动修复。原视频需要保留在 manifest 的 `source.original_path`；移动文件后不能静默换输入继续旧任务。
