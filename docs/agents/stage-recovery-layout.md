# 阶段入口、局部恢复与打印布局

准备任务后，调用 `stage`（可传 `title`）。默认 `mode=sparse`，先取首尾布局，再根据新增完整谱行及重叠自适应跳转；疑点区间缩小跳转，必要时局部连续扫描。`max_observations` 为单次向前观察及接续回查各自的操作预算，默认 128，范围 1–8192；预算用尽保存进度，返回来源阶段 pending，继续调用 stage。程序完成当前可自动执行的采集、来源检查、粗拼冻结和排版，然后返回下一项宿主或实际审阅操作。`phase` 为 `source`、`generation`、`pdf_review` 或 `complete`；`status` 为 `blocked`、`pending` 或 `complete`。响应包含产物引用、检查、未决项和 `next`。只有最终每页实际审阅已保存，才能返回 `complete`。

程序冻结的正常输入由 `stage` 或 `redraw-requests` 批量预留为 `prepared`，返回 `ready_to_dispatch`。使用每个 handoff 的 `group`、`request.request` 调用 `dispatch-redraw(identifier, request)`，保存 `calling` 后立即执行宿主生图，再以同一 request 回填 `finish-redraw`。重复读取已预留请求会返回相同 ID。重复 `stage` 遇到 `calling` 返回 `recover_existing_call`，先恢复已有结果，不能重新发送。无法恢复时用 `fail-redraw` 和具体原因转矢量。生成图返回后，实际查看并调用 `review-redraw`；拒绝后最多一次定向修正。

手动冻结的任务返回 `needs_input_review`。Agent 实际查看粗拼，运行 `crop-checks`，再通过 `redraw-requests(viewed_notes=...)` 批量预留。`begin-redraw` 保留单组入口，传 `reserve=true` 仅预留；省略时沿用旧行为，直接登记为 `calling`，按已提交处理。阶段入口不会创建看图备注。

尚未提交的 `prepared` 请求可以通过 `cancel-redraw(identifier, request, notes)` 作废为 `cancelled`，保留 ID、hash 和原因。修改选行或组成员时，失效输入的预留请求也作废；已提交的 `calling` 保留未知结果保护。作废初次预留后可重新预留新 ID；作废修正预留仍保留已占用修正额度并转矢量。旧 `calling` 不能仅凭没有结果降格为未提交。

有效历史手动冻结沿用其来源审阅，不重新扫描视频。历史新版任务若缺少 freeze，可通过 `assemble` 提交原相同选行和原审阅恢复；这是历史决定恢复，不是新的视觉审阅。保留原精确生图分组，即使其大小超过当前默认分组上限。旧程序扫描规则需要重新检查，不能凭旧 `complete` 标记继续。

## 导航、清单与证据

`row-manifest` 返回持久谱行清单。每条谱行包含稳定身份、独立排列顺序、当前来源、实际 PTS、时间基准、hash、裁剪、备用来源及接续依据。插入补采不重编号已有谱行；同位置去重，不同位置的重复音乐保留。清单元数据变化不重置生图输入额度，实际输入变化只影响对应组。

明确可读的小节顺序、完整行边界和首尾记号可以共同证明无重叠接续。导航缩略比较只决定跳转跨度；原生细节仍无法确认时登记 native_difference_needs_visual_review，交给 Agent 判断，不能用缩略相似度批准记谱或反复扫描同类微小差异。程序没有 OCR；Agent 实际查看两张原生截图后，通过 `review-continuity` 记录来源、小节范围、完整行和首尾判断。音乐、裁断或原谱位置风险仍阻止冻结，编号记录不能免除这些检查。

分别记录接续证据完整、严格时间覆盖和未决项。稀疏接续通过可以冻结，但不写成严格全曲覆盖。显式 `stage` 请求 `{"mode":"strict"}` 会连续扫描，即使此前已通过稀疏冻结。`overview`、`resample` 保留原连续扫描语义。连续扫描预算耗尽也不等同于完整覆盖。

旧协议任务不迁移；有效历史人工冻结不重新扫描。源码升级与宿主安装分别处理，修改仓库 Skill 不自动修改安装副本。

## 局部修改

使用 `revise-crop(index, bbox)` 或 `assemble` 发布选行。程序先验证裁剪并准备新文件，再原子发布记录；无效参数或发布中断保留上个有效记录。修订后必须重新通过来源、覆盖及裁剪检查，冻结前不能调用生图。通过后调用 `redraw-inputs`，沿用原组的成员数，或显式传入完整有序 `groups` 重新分组。

输入身份包含有序来源 hash、原生截图 hash、实际 PTS/time_base、原谱位置、裁剪 hash、bbox 和五线几何；文件路径、UUID、页码和打印布局不参与身份。只有实际成员与输入完全相同才能恢复结果。修改一行只建立相关组的新版本，其他组复用；A→B→A 恢复 A 的原调用、修正次数与接受结果，不退还额度。相同像素但不同原谱位置分别处理。所有旧版本保存在 `generation_history`，选择改变撤销当前 PDF 和批准，旧文件与元数据保存在 `output_history`。

## 布局与全部页面审阅

`layout` 接受 `margin`、`minimum_gap`（单位为 PDF 点，范围 0–144）和可选 `target_pages`（1–512）。默认边距 24、最小行距 6。布局调整只撤销当前 PDF 批准，保留所有生图材料、历史和额度。共同缩放以来源宽度为准，短行保留自然宽度，分页只发生于完整行之间。目标小于自然分页结果时保留更多页，响应 `layout.explanation` 说明完整行与可读比例约束。

两个公开导出入口 `export` 和 `reconstruction.export_vector` 都遵循当前布局与全部预览契约，在新版本目录输出 PDF、材料映射和每页 `preview-N.png`。Poppler 逐页限时渲染，最多 512 页，每页长边最多 1200 像素。`previews` 按页序列出 hash；`checks` 检查放置中的遗漏、同位置重复、边界、比例和重叠，异常留白作为 warning。这些是几何检查，不是全曲音乐校对；未选候选依据仍在来源检查记录中。

实际查看全部有序预览，检查标题、关键记号、顺序、首尾、裁断与观感，再调用 `review-pdf`，传入所有 `pages`、具体 `notes` 和当前 `output_revision`，即导出回执中的独立版本标识，不能使用 PDF sha256。缺少版本标识、缺页、过期版本或产物损坏拒绝批准。即使新旧 PDF 字节相同，新导出也需要新的版本标识和本次实际审阅。旧任务只有 hash 审阅时，调用 `stage` 或 `export` 生成新版预览，再查看全部页面并提交新标识。预览失败或发布中断不会替换已有有效输出；重新导出不覆盖旧文件。

验证证据分别记录：自动检查、受控回执、历史决定重放、实际模型生成和实际看图。受控 CLI 测试不证明真实生图；历史材料重排不计新调用。未知成本保持 `null`。真实来源未决保留 `blocked`，不能用矢量消除隐藏或无法确认的音乐。
