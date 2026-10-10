# 显式混合接受实验

`--script-acceptance` 只在新 `prepare --evidence-mode lazy` 任务建立时生效，固定策略为 `continuous_clean_v1`。默认 full 不变，已有任务不迁移。用户于 2026-10-10 确认兼容提案后，在隔离软件实验中实现此入口。真实自动接受支持范围仍为空，#45 的完整成本和 #52 的质量、耗时、总 Token 门禁仍待满足。

```sh
uv run --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt skills/bilibili-drum-score-to-pdf/scripts/convert.py /absolute/video.mp4 --output /absolute/new-task --evidence-mode lazy --script-acceptance
uv run --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt skills/bilibili-drum-score-to-pdf/scripts/convert.py --operation review-plan --task /absolute/new-task --output /absolute/new-plan
```

prepare 保存 waiting 观察包。review-plan 请求每个参与原帧的完整原生区域，生成未确认的构建模板。物化后重建计划，Agent 实际查看原生源 ROI，确认光标与遮挡，填写 `review.native_clean_regions`。脚本没有能力从像素证明任意灰色小遮挡、白色擦线或与音符相似的覆盖块不存在；缺少这个实际判断时保留 waiting。

每个 `native_clean_regions` 项只含 `frame_id`、`frame_sha256`、`pts`、`time_base`、`bbox`、`evidence_images`、`cursor`、`occlusion`、`evidence`。hash、PTS 与 time_base 必须匹配当前原帧。bbox 使用原生整数坐标，引用实际已呈交的同帧 detail/native_detail，并完整覆盖核查区域。cursor 与 occlusion 为 clear、present 或 uncertain，只有实际查看后才能填 clear。该判断覆盖脚本使用的完整行间带、实际执行框与必需 pair 的分析窗口，不能只查看调用方已缩小的打印框。

脚本接受普通 gap 时，对每个必需 pair 的两端分别重算检测器的行间带；外行使用完整谱面 ROI。每个端点须有同帧的 clear 记录，同时覆盖这一区域、观察框、对应所选行的精修执行框和 pair 分析窗口。Agent 已确认行与观察也不能替代 gap 的 clean 覆盖。只查看 `staff_y - 4 * spacing` 到 `staff_y + 8 * spacing` 的窗口时，gap 继续 waiting。

标题、速度、拍号、行外符号以及首尾完整边缘继续由 Agent 核查，使用现有 confirmations、原生图块与 score_audit。普通内部行、五线观察与相邻 gap 可交给脚本重算，保留其未确认字段即可。构建器会为通过的普通 gap 将 pending 改为 script；手动填 script 不能产生接受权威。未通过的项需实际审阅或补采，不能将 uncertainty 改成高置信度。

```sh
uv run --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt skills/bilibili-drum-score-to-pdf/scripts/convert.py --operation build-decision --task /absolute/new-task --decision /absolute/review-request.json --output /absolute/new-build
uv run --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt skills/bilibili-drum-score-to-pdf/scripts/convert.py --operation submit --task /absolute/new-task --decision /absolute/new-build/decision.json
uv run --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt skills/bilibili-drum-score-to-pdf/scripts/convert.py --operation export --task /absolute/new-task --output /absolute/new-export
uv run --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt skills/bilibili-drum-score-to-pdf/scripts/convert.py --operation replay --task /absolute/new-task --output /absolute/new-replay
```

## 脚本实际检查的范围

首版只支持一个固定比例、固定横向布局的连续谱面段。每帧从当前原图重新检测全部五线组，并核对观察数量、顺序、staff_y 与 spacing。缺少一组、不同合理位移或低重叠候选均保留 waiting；不利用内容或颜色删掉其他合理位移。至少两条有序重叠及共同位移仍使用原几何验证。

普通内部行的 ownership band 由前组五线末线与本组首线的中点、本组末线与后组首线的中点界定，横向包含检测到的完整谱面 ROI。两端各四行必须是纯白原生像素。脚本检查这整段区域中每个非白像素，打印建议与执行框都必须保留全部占据像素。一个断开的细小符号也不能因面积小而丢弃。首尾行缺少两侧邻组，继续由 Agent 确认。缩小原建议框的精修不在此脚本范围，交给 Agent 原生复查。

严格纯白切带可能因压缩噪声、灰底或边缘像素而失败。这是保守等待，不按 codec、视频 ID 或歌曲颜色增加例外。候选颜色、白底比例与已有光标/遮挡检测只否决候选可用性，不证明身份或排除任意遮挡。实际原生 clean 判断始终保留 Agent 权威。

全部必需相邻 pair 还要通过可靠的局部内容否决检查。`not_contradicted` 只表示未发现冲突，不证明同一行；conflict 与 uncertain 均等待。污染旧 pair 后新增干净源不能绕过旧对应。重复音乐按独立空间实例保留，部分行、错序、缺行、换页、布局变化、导航限额或未解决 gap 不自动解除。

## 旁记录、来源与恢复

构建器输出 `acceptance.json`，绑定 task_id、观察 hash/version、源 hash、精确决定文件 hash 与固定策略。items 使用现有 segments/rows/observations/transitions 路径，保存 script 权威、实际同帧原生区域、规则结果与未决项。`native_clean_regions` 独立保留 Agent 实际判断及原生来源。调用方填写 passed 或修改保存检查结果不能替代重算。保存的 `sources.json` 与 CLI 返回的 sources 包含相同的 `script_acceptance_items`。

有脚本项时决定的全局 `visual_review=false`，脚本读取不会加入 presented_images。所选行来源分别记为 `script_acceptance` 或 `visual_judgment`。submit、export、replay 与重复混合提交复用同一验证入口，重新计算旁记录、几何、内容与整曲审计，再执行原裁剪、150 effective DPI、灰度和整行分页门禁。普通 gap 仍逐项保留，`hidden_content_proven_absent=false`。

接受历史保存决定、审计、接受旁记录与各自 hash。物化或补采改变观察版本后，旧绑定失效；修改 bbox、来源或对应关系须显式 revision_of 最新接受决定并重绑。实际判断的历史复用仍须显式启用，并验证同一源、同一帧、未改呈交证据与结构。新采原帧不自动继承旧 clean 判断。

报告分别记录脚本接受项、Agent clean 区域、未决脚本项、实际原生读取像素及所有完整帧分析。`full_frame_analysis_attempts` 统计 `native_analysis`；ROI 五线复核保存为独立 `native_staff_recheck` 阶段，由 `native_staff_recheck_attempts` 统计。两类尝试均保留失败次数与阶段耗时。生成图像、脚本读图与模型实际呈交分别记账，未知宿主 usage 与总 Token 保持 null。首版省掉部分普通行重复判断，仍需要实际源 ROI 审阅，不保证总 Token 或端到端时间下降。

关闭开关，在新的结果目录运行默认 full prepare；保留实验任务、历史、决定与日志。`--script-acceptance` 与 convert、resume 或其他旧任务操作组合会拒绝。也可在独立 checkout 使用冻结稳定代码 `d09fa9d` 和新的任务目录回退。

显式最小证据链是另一个独立的新任务开关，契约见[内容接续证据](content-checks.md)。它不扩大此脚本接受策略的严格几何和原生切带范围；混合 gap 本身不符合脚本权限时，仍由 Agent 实际核查与原覆盖审计承担。不得把内容链的两个锚点当作任意原生 clean 或唯一位移证明。
