---
name: bilibili-drum-score-to-pdf
description: 将 B站链接或本地纵向滚动鼓谱视频转成长截图，优先生图或矢量兜底，整理为允许局部推测的 A4 PDF。
---

# 鼓谱视频转 PDF

交付以实际谱名命名的 A4 PDF。流程为下载视频、自动长截图、清理重绘、完整谱行排版。允许模型根据上下文推测模糊或遮挡的局部符号，交付时统一说明可能存在推测。

显式选择本 Skill 并提供视频链接，即执行 PDF 流程。未指定输出位置时，在当前工作目录建立独立任务目录，保留已有同名文件。交付时报告 PDF 绝对路径。

从本文件实际位置确定 Skill 根目录。需要 Python 3.12、uv、ffmpeg、ffprobe、Poppler 和图片查看能力。使用隔离依赖环境，`<skill-root>` 替换为本文件所在目录的绝对路径：

```sh
uv run --python 3.12 --quiet --isolated --with-requirements "<skill-root>/scripts/requirements.txt" \
  python "<skill-root>/scripts/convert.py" '视频链接或本地视频路径' --output /absolute/new-task
```

## 正常流程

1. 准备后调用 `stage`，程序生成长截图和整行切分。查看长图及原生首尾，检查明显漏行、重复和裁断，通过 `review-longshot(title, notes)` 记录一次整体审阅。蓝标、水印、局部模糊和轻微接缝直接进入后续处理，不逐符号校对或逐行填写来源。整小节、整行缺失修复拼接，不能凭空补写整段音乐。
2. 再调用 `stage`，按全部 handoff 的组 ID 和 request ID 执行 `dispatch-redraw`，真实调用宿主生图，以同一 request 回填 `finish-redraw`。请求已包含清理提示词。查看生成结果，通过 `review-redraw(accepted, notes)` 判断明显增删行、裁断和整体可读性，程序自动取得行边界。每块最多一次定向修正，小疑点不阻止交付。
3. 生图工具不可用或明确失败时，对相应组调用 `fail-redraw` 转矢量。调用结果未知时先恢复原调用；无法恢复再记录 `unknown`。轮廓转描保留可见外形，不能补出隐藏音符。
4. `stage` 导出 A4 和全部有序预览。实际查看每页，检查谱名、首尾、明显漏行或重复、裁断和排版，通过当前 `output_revision` 调用 `review-pdf`。`stage.phase=complete` 后交付，统一说明“近似重绘，局部符号可能含模型推测，未经逐符号校对”。

长图过长时自动按完整谱行分组，生图分组与 A4 分页分别处理。需要重拼、一次修正、恢复调用或调整布局时，读取 [stage-recovery-layout.md](references/stage-recovery-layout.md)；请求字段读取 [reconstruction-entry.md](references/reconstruction-entry.md)。`--summary` 的 `details.path` 保存完整回执，读取后取得全部请求和产物。

首版支持已有白底多行、固定比例的纵向滚谱，优先适配停驻后向上推进。缩放、横移、复杂翻页及没有谱面的演奏视频不纳入首版。无法查看图片时如实报告。匿名获取和宿主检查见 [support.md](references/support.md)。
