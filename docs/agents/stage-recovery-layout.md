# 阶段恢复与打印布局

`prepare → stage` 自动生成长截图和完整谱行切分。Agent 只在整体长图、真实生成结果及最终页面三个位置作视觉判断。

| phase | 下一步 |
| --- | --- |
| longshot_review | 查看长图及原生首尾，review-longshot 提交 title、notes |
| generation | 执行或恢复全部 handoff，整体查看生成结果 |
| pdf_review | 查看当前版本全部预览，提交 review-pdf |
| complete | 当前 PDF 已逐页查看，可以交付 |
| source | 旧手动任务的来源恢复；新任务使用长截图 |

## 长图与重拼

长图、样本实际 PTS/time_base、位移记录和原生首尾分别保存于版本目录。程序不会固定擦除右上角、裁掉两侧或删除浅色标记。整体检查明显漏行、重复、裁断；蓝标、水印和局部模糊不阻止交付，不逐符号填表或证明音乐等价。

发现明显拼接问题时用 `review-longshot(accepted=false)` 记录原因，再用 `stitch` 重拼。默认每秒采样，最大垂直位移400像素；确有接续问题时可调整 interval 或 max_jump。旧长图保留，重拼撤回其整体批准及当前 PDF，保留调用历史。正在运行的宿主调用先恢复，避免重复调用。

整小节或整行缺失优先修复拼接，不凭空补写整段音乐，也不将已知缺段称为完整谱。局部符号可由生图根据上下文推测，交付说明统一披露，不逐符号记录假设。

## 生图与一次修正

整体长图通过后，`stage` 自动预留全部组，返回 `ready_to_dispatch`。按 handoff 的 group 和 request.request 执行 dispatch-redraw，实际调用宿主生图，再用相同 request 回填 finish-redraw。后者的 tool 固定为 host-imagegen，receipt 保存实际调用依据。prepared 是尚未发送，calling 是已登记调用；重复 stage 返回同一 ID。recover_existing_call 先恢复已有结果，不重新发送。

查看生成结果后提交 review-redraw 的 accepted 和 notes。长截图路线自动检测行边界，无需 Agent 手工逐行画框；显式 boundaries 仅用于检测无法适配时的恢复。明显行数变化应定向修正一次或转矢量。

拒绝初次结果后，begin-redraw 传 correction=true、viewed_notes，执行一次修正。修正后仍不合适，或者工具不可用、失败、未知结果确认无法恢复时，用 fail-redraw 和具体 outcome 转矢量。小疑点不阻止接受现有结果。矢量只转描可见外形，保留原有重复音乐，不承担音乐语义恢复。

## 布局与终稿

layout 接受 margin、minimum_gap，单位为 PDF 点，范围0–144；可选 target_pages。默认边距24、最小行距6。布局只撤销当前 PDF 批准，复用原生图、生图结果及修正次数。统一比例重排，只在完整谱行或连续行组之间分页；目标页数过少时保留实际需要的更多页面。

每次导出保存独立 exports/<revision>/、PDF、材料清单和全部按序 preview-N.png，不覆盖旧结果。程序检查页边界、比例、顺序、重复和重叠，不做音乐校对。

实际查看全部预览，提交 review-pdf 的 pages、具体 notes 和当前 output_revision。版本标识不是 PDF hash；新导出使用新版本，旧审阅不能批准新文件。近似输出附 notice、reliable=false，表示没有逐符号音乐等价保证。未知模型成本保留 null。

## 旧手动任务

已有手动任务继续恢复其来源和调用历史，不自动重新拼接。只有明确恢复旧任务时才使用 capture、present、assemble 及 revise-selection/revise-crop；这些操作保留原有手动来源约定。新任务按上述长截图流程推进。
