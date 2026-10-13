# 本地视频的几何矢量还原

本页描述 Issue #55 的新本地工作流边界 `reconstruction.py`。Agent 查看原图、选择有序完整谱行、确认谱名和完整性，然后调用本地工具导出矢量 A4 PDF，再实际查看每页 PDF。用户只提供视频和输出位置，无需编写 JSON。

此模块尚未切换默认入口。宿主生图、导航、公开视频统一入口和旧模块删除在后续工单完成。本地工具不能执行视觉判断，也不能证明音符音乐语义等价。

## 前提

使用仓库已固定的 `requirements.txt`。取帧依赖 `ffmpeg` 和 `ffprobe`，PDF 检查可用 Poppler 的 `pdftoppm` 与 `pdfimages`。无需新增依赖、模型认证或 MIDI 依赖。

为每个任务选择新的空目录。恢复时保留 `record.json` 引用的原视频与任务目录，原视频暂不复制到任务中；移动或改变原视频会阻止恢复。当前格式不接受旧任务记录。

## Agent 操作

在 Python 中导入 `skills/bilibili-drum-score-to-pdf/scripts/reconstruction.py`，按顺序调用以下接口。

1. 调用 `prepare(source, task)` 探测本地视频，建立来源 SHA-256 与轻量任务记录。已有有效任务可以恢复；已有用户文件的未知目录会被拒绝。
2. 调用 `capture(task, seconds)` 保存原生截图与实际 PTS、时间基准和 SHA-256。相同请求时间复用截图。解码失败也保存实际尝试数量与耗时，继续沿用 `VideoReader` 的累计解码保护。
3. 实际查看截图，按原谱空间顺序选择完整谱行。移除同位置截图重叠，保留后来出现的重复音乐。确认标题、署名、速度、拍号、行外记号和首尾。遮挡导致内容不可读时，在 `unresolved` 中记录疑点并局部补采。
4. 调用 `assemble(task, title, regions, review)` 保存选行、原裁剪与粗拼图。程序不会代替 Agent 判断连续性。
5. 调用 `export_vector(task)` 转描轮廓、补五线并按完整行分页。输出处于 `needs_pdf_review`，不能直接称已审核。
6. 用 `pdftoppm` 渲染并实际查看最终每页，检查来源顺序、记号、首尾、裁断、重叠与留白。调用 `review_pdf(task, pages, notes)` 记录实际看图结果；`pages` 必须包含每页。

`regions` 是 Agent 提交的有序列表，每个条目包含以下字段。

| 字段 | 意义 |
| --- | --- |
| `capture` | `capture()` 返回的 `id` |
| `bbox` | 原生截图中的 `[left, top, right, bottom]` 整数坐标 |
| `kind` | `header` 或 `system`；标题只放在列表首项 |
| `staff_top` | `system` 中第一条五线距裁剪顶部的像素位置 |
| `staff_spacing` | 原裁剪中的五线间距 |

`review` 包含 `viewed_captures`、`complete` 和具体 `notes`。只有实际查看的截图 ID 能进入选行。存在未决内容时填写 `unresolved`；程序拒绝导出。`complete` 是 Agent 对选定范围的明确陈述，程序不能验证未采集的视频内容。片段验收要另记 `scope`，不能声称整曲已完成。

例如，Agent 看到标题和一行完整谱面后可提交以下记录。坐标必须来自该次实际截图，不能套用示例。

```python
shot = capture(task, 0)
# Agent 此时实际查看 shot 对应的原生图像。
assemble(task, confirmed_title, [
    {"capture": shot["id"], "bbox": [0, 0, 640, 65], "kind": "header"},
    {"capture": shot["id"], "bbox": [0, 65, 640, 180], "kind": "system",
     "staff_top": 35, "staff_spacing": 10},
], {"viewed_captures": [shot["id"]], "complete": True,
    "notes": "实际检查标题、速度、拍号和完整首尾。"})
result = export_vector(task)
# Agent 渲染并实际查看 result 中的所有 PDF 页面。
review_pdf(task, list(range(1, result["page_count"] + 1)), checked_notes)
```

## 来源与边界

`record.json` 区分原视频、原截图、原裁剪、粗拼图和几何矢量派生产物。截图和裁剪保留实际 PTS；派生产物记录输入 hash。读取任务时重新检查视频、截图、裁剪、粗拼、矢量记录和 PDF 的 hash。修改选行使用版本化文件，不会在后续选择验证失败时破坏原接受内容。每次导出保存到任务内 `exports/<revision>/<实际谱名>.pdf`，`output.pdf` 是相对任务目录的路径。相同当前产物通过 hash 检查后复用。重新选行后导出新的版本，保留原 PDF；写完 PDF 后任务记录保存中断时，也能恢复并导出新版本。未知用户同名 PDF 不会被覆盖。矢量记录与 PDF 存在同一导出版本目录。

矢量路线沿用已认可实验的暗色与饱和色轮廓规则，把可见高亮记谱转为黑色，忽略浅色播放背景。该规则不保证清除任意水印或深色播放边框。五线位置由 Agent 看图确认，水平线探测只用于确定可见端点；不可确认时报告疑点。完全隐藏的符号不能恢复。

PDF 只使用路径和直线，不把粗拼图嵌入成位图。所有系统采用共同等比例缩放；短末行保留短宽度，完整谱行之间分页。正常页均匀分配间距，稀疏页限制过大行间距并上下平衡留白。单行超过可打印高度或粗拼超出当前内存范围时，程序拒绝处理。当前大谱分段粗拼尚未实现。

`review_pdf()` 只保存调用者的实际审阅陈述。调用成功不能证明看过图，也不能证明音乐等价。`model_cost` 保持 `null`。

## 验证记录

重构基线为 `51aa468`。新工作流在独立工单 worktree 开发，未修改原实验和旧默认入口。运行以下聚焦验证。

```sh
uv run --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt \
  python -m unittest discover -s tests -p test_reconstruction.py -v
```

测试通过同一工作流边界覆盖正确命名的矢量交付、无效媒体、原视频/截图/裁剪/矢量损坏、未决内容拒绝、失败选行保护、用户目录保护、失败 seek 成本保存，以及重复音乐和短末行的三页 A4 排版。另覆盖已审核同谱名重选的再次导出、PDF 写完后任务记录保存中断的恢复；两种情况都保留历史产物，恢复不重新采集或重置预算。首个交付测试与来源保护修复保留了实际 red→green 过程。测试使用 ffmpeg 生成的受控谱面视频；测试中的审阅陈述只用于验证状态行为，不算真实视觉验收。

2026-10-13，另以既有 KiLLKiSS 实验源视频起始 0.2 秒的无音频拷贝作小范围样本，只验收完整第 1–15 小节。没有声称整曲完成。实际查看原生截图和最终一页 Poppler 1600 像素渲染，核对 KiLLKiSS、Ave Mujica、陈老师、四分音符速度 200、4/4、首行和 6/12 行号、10–11 多小节休止、末小节 15 及蓝色休止符转黑。未见裁断、重叠或重复行；短片段上下留白平衡。`pdfimages -list` 无位图项。

现场产物位于仓库外 `/tmp/issue54-context/pdf-acceptance/`，可供本次集成复核，不是永久交付位置。任务记录保存全部来源 hash、实际 PTS `0`、时间基准 `1/16000`、1 次 seek、解码器报告 2 帧、实际呈交 1 张原截图和逐页审阅陈述。完整帧视觉分析为 1 张，不能把解码器报告帧数称为实际看图数量。本次未调用生图或 MIDI。PDF SHA-256 为 `4f19226d9bead2a94a343f22366abc79f683aabba67b40845d3bcefec58bf57c`。

该次实看记录绑定以下原材料 hash，位于同一 `record.json`。

- 小范围视频 SHA-256 为 `4f9b46b56d240434fe38170098db6fa9cd85e91f0c1a0d920091dc2372dd1335`。
- 实际呈交原截图 SHA-256 为 `d0013fdd3426e5394252afda99571adcce59cefa5cb799e8c148035cb6f1f5e5`。

`pdfimages -list` 实际输出只有表头与分隔线，没有图像对象；原生截图和 PDF 并非像素相等，轮廓转描属于派生几何重绘。

规格审阅指出顶层固定 PDF 名会阻断重选和中断恢复。修复用版本化导出目录消除该冲突。两项反例在修复前基线实际失败，修复后 11 项专项测试通过。中断测试使用受控持久化失败，不算真实宿主生图、视觉审阅或整曲验收。
