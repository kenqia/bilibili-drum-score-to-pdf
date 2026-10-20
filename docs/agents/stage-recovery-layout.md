# 阶段恢复与打印布局

新任务 `prepare → stage` 自动生成长截图和完整谱行切分，默认原图直排。整体查看长图后直接排版，实际查看最终全部页面后交付。

| phase | 下一步 |
| --- | --- |
| longshot_review | 查看长图及原生首尾，review-longshot 提交 title、notes |
| pdf_review | 查看当前版本全部预览，提交 review-pdf |
| complete | 当前 PDF 已逐页查看，可以交付 |
| generation | 可选重绘或旧任务的宿主执行与实际审阅 |
| source | 旧手动任务的来源恢复；新任务使用长截图 |

## 长图与来源恢复

长图、实际采样 PTS/time_base、位移和原生首尾分别保存。长图是多帧处理的派生产物，不是未经处理的原生截图。整体检查明显漏行、重复、裁断；轻微模糊、底色、播放标记和残留水印不阻止直排，不逐符号填表或证明音乐等价。

明显拼接问题用 `review-longshot(accepted=false)` 记录原因，再用 `stitch` 重拼。默认每秒采样，最大垂直位移400像素；确有接续问题时可调整 interval 或 max_jump。重拼使用新目录，撤回长图及当前 PDF 批准，原长图、调用历史和额度保留。

严重遮挡优先用 `capture(seconds)` 取得实际原帧，实际查看后用 `repair-longshot` 提交 capture、帧内 bbox、长图内 target_bbox、当前 source_sha256 和 notes。两个矩形必须同尺寸，程序按长图色彩模式复制来源像素，不缩放或生图。修复保存原长图及补采 PTS/time_base/hash，重新切分并返回 longshot_review。恢复后重新整体审阅，不恢复逐行来源填表。

整小节、整行缺失先修复拼接，不凭空补写。仍有严重缺损时说明具体限制；已知缺段不能称完整谱，也不能通过接受审阅把缺段记录成完整。

## 局部去水印

原图路线整体审阅通过后，实际确认清理区域没有音符、五线、标题和署名，再调用 `clean-watermark(rectangles, source_sha256, notes, confirmed_safe=true)`。rectangles 是长图坐标的整数矩形列表，右下边界不包含在区域内，最多128项。source_sha256 填当前未经去水印的 longshot.image.sha256。

程序从该长图生成独立清理图，将指定区域填白，验证区域外像素未变。confirmed_safe 和 notes 是 Agent 的实际视觉判断，像素一致性不能证明区域内没有记谱。无法确认时保留水印。重叠水印不擦除、不补画。

每次列表替换当前全部清理区域，不累计到上一次清理图；提交空列表恢复未经清理的长图。原图、清理图和修改记录保留。清理变化撤销当前 PDF 批准，再用 stage 导出并查看全部页面。重拼或局部来源修复后，旧清理不自动套用新长图。

## 明确请求后的重绘与矢量

用户明确要求时调用 `pdf-route(route, notes)`，route 为 redraw、vector 或 original；notes 记录实际请求。切换路线撤回当前 PDF 批准，保留历史结果和调用额度，不自动调用模型。已有 calling 先恢复结果，再切换路线或修改来源。显式调用既有 redraw-inputs、redraw-requests、begin-redraw 或 dispatch-redraw 同样表示选择重绘；export_vector 表示选择矢量，后续 stage 保留该选择。来源修订保留已选择的重绘或矢量路线。即使历史记录的路线字段与 calling 不一致，stage 也优先呈交已有调用，不新建请求或隐藏未决结果。

redraw 路线整体长图通过后，stage 预留全部组，返回 ready_to_dispatch。按 handoff 的 group 和 request.request 执行 dispatch-redraw，实际调用宿主生图，再用同一 request 回填 finish-redraw。tool 固定为 host-imagegen，receipt 保存真实依据。prepared 尚未发送，calling 已登记调用；重复 stage 沿用原 ID，recover_existing_call 先恢复已有结果，不重发。

查看生成图后用 review-redraw 提交 accepted、notes。长图路线自动检测行边界，boundaries 仅在检测恢复时显式提交。明显增删行拒绝后可 begin-redraw(correction=true, viewed_notes) 定向修正一次。工具不可用、失败或未知结果确认无法恢复时，fail-redraw 和具体 outcome 转矢量。每组每输入版本一次修正，不因恢复退还额度。

vector 路线直接转描原长图的可见轮廓，不申请生图；既有重绘组失败后的矢量兜底继续可用。轮廓转描不能恢复隐藏记谱，也不代表音乐识别。

## 布局与终稿

layout 接受 margin、minimum_gap，单位为 PDF 点，范围0–144；可选 target_pages。默认边距24、最小行距6。统一比例，只在完整谱行或连续行组之间分页，先自然分页再平衡相邻页留白。页数目标仅作结果对照，不强制等高切图、每页同行数或增加空白页。布局复用当前材料和修正次数，撤回旧 PDF 批准。

每次导出保存独立 exports/<revision>/、PDF、材料清单和全部按序 preview-N.png，不覆盖旧结果。程序检查页边界、比例、顺序、重复和重叠，不做音乐校对。

实际查看全部预览，提交 review-pdf 的 pages、具体 notes 和当前 output_revision。新导出必须重新审阅，PDF hash 不能替代版本标识。原图 notice 说明未经逐符号校对及来源限制，生图说明局部推测，纯矢量说明仅保留可见外形；reliable=false 不声称音乐等价。未知模型成本为 null。

## 旧任务恢复

已有任务未记录 pdf_route 时沿用重绘路线，不自动切为原图或重新拼接。旧手动任务继续使用 capture、present、assemble 及 revise-selection/revise-crop 的来源约定。新长图局部补采使用上述 repair-longshot。所有路线沿用来源 hash、匿名网络、资源期限、路径和输出不覆盖保护。
