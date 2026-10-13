# Agent 的截图、重绘与 PDF 工作流

`score_workflow.py` 是 Issue #56 的工作流接口。用户提供公开 B站链接或本地视频，Agent 负责导航、看图、确认接续、调用真实宿主生图并审阅 PDF。用户无需选择路线或填写任务 JSON。正式默认入口由 Issue #59 切换；现有默认入口暂时保留。

## 准备与采集

使用项目现有 `requirements.txt`、`ffmpeg` 和 `ffprobe`。最终逐页检查使用 Poppler。没有新增模型认证、付费 API 或依赖。

1. 调用 `prepare(source, task)`，其中 `task` 是新的空目录。公开 URL 沿用匿名下载、分 P、网络校验、下载期限与媒体资源保护。本地视频与 URL 在获取后使用同一任务记录。恢复时再次传入同一视频或等价的规范 URL，不会重复下载。
2. 调用 `navigate(task, seconds, width=480)` 保存低清导航图。实际查看导航图，判断谱面是否推进，然后决定下一次导航时间。时间由 Agent 根据画面决定，不使用固定采样间隔。
3. 对主要推进位置调用 `capture(task, seconds)` 保留原生截图。截图记录实际 PTS。静态停留和光标移动不要求继续保留原生截图。发现缺口时，有目的地补采缺失位置；不为每个疑点设固定补采轮数。
4. 实际查看原生图，用 `present(task, identifiers, notes)` 记录已呈交的截图或导航图。低清探测、原生截图与实际呈交数量分别保存。保存文件不等于看过图。

## 确认接续并粗拼

调用 `assemble(task, title, regions, review)`。`regions` 使用[本地工作流的裁剪字段](reconstruction-local.md)，并增加每个原谱空间位置的 `position` 字符串。相同位置的重复截图只保留第一项；后续出现的重复音乐使用另一个位置标签。标签由 Agent 看图提出，不从像素相似度推导。

`review` 除已查看来源、完整性和具体备注外，必须记录 `continuity` 与 `first_last`。确认相邻截图重叠、上滚或有序翻页接续，检查视频前后无谱区间和最后完整谱行。半行在取得完整来源之前不能纳入。标题、速度、拍号、行外记号与短末行也要保留。水印、高亮或蓝色播放矩形本身不会导致拒绝；遮住关键内容时记录 `unresolved`，局部补采后再确认。

不能确认的接续应保持 `complete=False` 或填写 `unresolved`，程序不生成成功 PDF。片段演示在记录中明确 `scope`，不能称为整曲交付。原裁剪保留完整；粗拼根据内存像素边界分块，`rough_chunks` 按原谱顺序列出全部材料。

## 调用宿主生图

调用 `redraw_inputs(task)`，取得按完整谱行划分的可审阅输入页。必要时传入 `groups`，每个分组是一组连续 region 索引，全部分组必须按顺序覆盖全部材料。

对每页依次执行以下操作。

1. 实际查看粗拼输入。调用 `begin_redraw(task, page_id, viewed_notes)`，先保存请求和输入 hash。
2. 调用真实宿主 `image_gen`，以返回的输入路径作为编辑来源。要求保留原图的音符、谱位、节奏、符梁、附点、鼓谱符头、标题与关键记号。程序只管理产物与状态，不代替宿主执行模型调用。
3. 工具返回后调用 `finish_redraw(task, page_id, request, output_path, 'host-imagegen', receipt)`。`receipt` 记录此次真实调用的标识和来源。复制原有 PNG 或受控 mock 不能计入真实生图验收。
4. 实际查看输出图。合格时调用 `review_redraw(..., accepted=True, notes=..., boundaries=...)`。`boundaries` 是输出图中每个完整标题块或谱行的整数边界，数量必须等于该输入页的 regions 数量，不能重叠或越界。
5. 初次不合格时调用 `review_redraw(..., accepted=False, notes=具体差异)`，随后调用 `begin_redraw(..., correction=True)`，执行一次定向修正。修正预算在工具调用之前保存，中断不会重置。修正后仍不合格，审阅接口自动将该页标记为 `vector`。

宿主不可用、调用失败或中断后无法确认调用结果时，调用 `fail_redraw(task, page_id, notes)` 转入矢量兜底。已接受的输出不能被迟到的失败记录降级。同一任务可以混合使用生图与矢量路线。

## 重排、逐页审阅与恢复

所有页处于 `accepted` 或 `vector` 后，调用 `export(task)`。矢量页沿用轮廓与五线转描；生图页按实际确认的完整边界裁切显示。PDF 用裁切和比例变换嵌入原生输出，不先重采样图片。两条路线统一计算 A4 纵向分页，共同打印宽度、等比例缩放，在完整谱行之间分页。稀疏页限制间距并平衡上下留白，不拉伸谱行或生成额外音乐。

输出保存到 `exports/<revision>/<实际谱名>.pdf`，同目录的 `materials.json` 记录来源、路线与最终放置。用 `pdftoppm` 渲染，实际查看每页，检查顺序、标题、速度、拍号、关键细节、首尾、裁断、重叠与留白。最后调用 `review_pdf(task, pages, notes)`，`pages` 必须列出每页。程序完整性检查与实际看图陈述分别保存。

恢复时保留原视频、任务目录与引用产物。读取会验证原视频、截图、导航图、粗拼、生成图、矢量记录和 PDF 的 hash；改变或损坏的材料不复用。相同标题、位置、裁剪和五线参数的 `assemble` 重入保留已经接受的生图、修正次数与 PDF。改变材料或撤回完整性确认后，重新建立派生产物；旧文件仍保留。任务不兼容旧 workflow 格式。模型成本未知时保持 `null`。

## 验证边界

```sh
uv run --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt \
  python -m unittest discover -s tests -p test_score_workflow.py -v
```

测试通过公共工作流接口检查规范 URL 恢复、低清导航与原生截图计数、重复位置去重、后来重复音乐保留、粗拼分块、修正预算恢复、调用失败与修正后拒绝的矢量路线、生成图与矢量的两页重排、未决接续拒绝，以及生成产物损坏。测试中的工具回执和看图备注属于受控夹具，不算真实工具或视觉验收。
