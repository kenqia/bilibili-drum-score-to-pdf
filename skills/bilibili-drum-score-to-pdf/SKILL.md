---
name: bilibili-drum-score-to-pdf
description: 将 B站链接或本地视频中的白底多行鼓谱整理、清理重绘并重排成完整 A4 PDF。
---

# 鼓谱视频转 PDF

交付以实际谱名命名的完整 A4 PDF。Agent 负责看图、判断接续和选择完整谱行，随包脚本负责获取视频、取帧、裁剪、拼接、矢量兜底和排版。

显式选择本 Skill 并提供视频链接，即执行 PDF 流程。未指定输出位置时，在当前工作目录建立独立任务目录；交付时报告 PDF 绝对路径，保留已有同名文件。

从本文件位置确定 Skill 根目录。需要 Python 3.12、uv、ffmpeg、ffprobe、Poppler 和原生图片查看能力。使用隔离依赖环境；命令及请求字段见 [reconstruction-entry.md](references/reconstruction-entry.md)。下面的 `<skill-root>` 替换为本文件所在目录的绝对路径：

```sh
uv run --python 3.12 --quiet --isolated --with-requirements "<skill-root>/scripts/requirements.txt" \
  python "<skill-root>/scripts/convert.py" '视频链接或本地视频路径' --output /absolute/new-task
```

## 取谱与选行

1. `prepare` 后调用 `stage`，读取已有截图、首尾采样建议和来源审阅模板。
2. 查看原生首尾图，确认谱名、音乐起点和末尾。根据重叠谱行、可读的小节编号或有序翻页补采中段，直到全部谱行的顺序有依据。截图数量由实际缺口决定。
3. 实际查看所选原生图后调用 `present`。使用 `assemble` 提交按原谱顺序排列的选区，每个选区包含明确 `position`。同一原谱位置选择一个完整来源；不同位置的重复音乐全部保留。
4. 裁剪包含该行所有音符、行外记号及适当白边。上下记号交错时保留连续行组。填写一份具体来源审阅，说明标题、首尾和跨截图接续；无法确认的内容写入 `unresolved` 并局部补采。
5. 再调用 `stage`。只修正实际看图或 `crop-checks` 指出的选区；已有工具能提供检查结果时直接使用。音乐未被遮住的播放标记或水印可进入粗拼，清理留给重绘阶段。

## 清理与交付

1. 查看每组粗拼，通过 `redraw-requests(viewed_notes=...)` 获取全部生图请求。按 handoff 的组 ID 和 request ID 调用 `dispatch-redraw`，随后真实调用宿主生图，并用同一 request 回填 `finish-redraw`。
2. 实际查看生成结果，对照原谱检查符号、行数和顺序。通过 `review-redraw` 提交接受决定及每行边界；每组每个输入版本最多一次定向修正。
3. 工具不可用时，调用 `redraw-inputs` 后对各组 `fail-redraw(outcome=unavailable)`。明确失败用 `failed`；结果未知时先恢复现有调用，确认无法恢复再用 `unknown` 转矢量。仍在运行的调用继续等待其结果，保持同一调用身份。轮廓转描只保留可见外形，不能补出被完全遮住的符号。
4. `stage` 导出 A4 PDF 和全部有序预览。实际查看每页的标题、顺序、首尾、关键记号、裁断、重叠和留白，传入当前 `output_revision` 调用 `review-pdf`。只有 `stage.phase=complete` 才交付。

局部替换、恢复调用、调整分页或回收已有结果时，读取 [stage-recovery-layout.md](references/stage-recovery-layout.md)。使用 `--summary` 时，从回执的 `details.path` 读取完整材料，获取全部请求和产物。

只支持已有谱面、固定比例、白底多行、向上推进或可确认有序翻页的视频。没有谱面的演奏视频、无法确认接续或隐藏音乐的来源，应报告具体限制。无法查看图片时如实报告，不能登记实际看图。

匿名获取失败时使用程序返回的脱敏诊断；公开 API 恢复由程序有界执行。运行边界及 Windows 注意事项见 [support.md](references/support.md)。
