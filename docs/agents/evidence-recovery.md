# 先找原帧，再恢复接续

`--evidence-recovery` 是新 lazy 任务的显式实验开关，须同时启用 `--minimum-evidence-chain`。任务固定 `clean_sources_v1`，默认 full、旧任务和原 `ordered_anchors_v1` 规则保留。可以同时使用 `--script-acceptance`；身份仍由 Agent 根据实际原图提出，脚本检查五线位置、空间顺序和完整覆盖。

已有成功 full 任务时，先复用它的真实原帧及实际 PTS。新任务不会继承旧任务的视觉判断、呈交记录或接受历史。

```sh
uv run --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt skills/bilibili-drum-score-to-pdf/scripts/convert.py --reuse-task /absolute/full-task --output /absolute/new-lazy-task --evidence-mode lazy --minimum-evidence-chain --evidence-recovery --script-acceptance
uv run --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt skills/bilibili-drum-score-to-pdf/scripts/convert.py --operation candidate-plan --task /absolute/new-lazy-task --output /absolute/candidates
```

复用入口核对源视频、观察包、原帧和接受历史。它不重跑导航，不 seek，复制原生帧和受校验的独立源视频，并重新生成任务观察包。保留原采样预算与实际 PTS，历史采样写入 `recovery_seed`。有接受决定时，清空全部正面判断和旧原生细节引用，生成 `seed-proposal.json` 作为空间结构建议。没有接受决定时，需要调用方提供结构。

`candidate-plan` 输出每个实例的既有候选、原帧 hash、实际 PTS、bbox、像素预检查及下一步。可提供严格绑定请求，字段仅为 `schema_version=1`、`task_id`、`observation_sha256`、`observation_version`、`proposal`。候选及旧身份没有自动视觉权限。先实际检查候选的完整原生区域；边界缺一两个像素时明确修订框并同步身份观察，不静默缩窄。只有仍缺干净来源或可靠接续时，才申请原有 30 秒以内局部补采。禁止重新扫完整首视频来替代局部定位。

## 污染观察与接续证据

每个相邻区间仍须有两个独立、有序、可信的空间对应，且每个对应都覆盖整个区间。两个对应可来自不同端点边。每条边必须经过全部共同实例的内容检查；中间帧不得丢失实例、改变比例或违反共同位移。partial 中间观察只有完整五线仍在框内时才能传递几何，不能打印或作为清晰内容端点。

一个污染或截边比较可以成为保留的诊断，前提是该区间双锚点成立，而且同一空间实例有完整、实际审阅且像素预检查可靠的干净来源。单个干净来源只能承担该实例的完整来源证明，不能代替区间的两个内容比较。未知遮挡声明、明确内容冲突、窗口高度或间距错配继续否决。任何失败比较都留在 `content_checks`，记录 `blocking` 和 `replacement_evidence`，不删除，也不把失败结果改成通过。

Agent 只对实际呈交的同帧原生区域填写 clear/present/uncertain。水印落在空白和水印覆盖音符须分别判断；清晰声明不能覆盖局部未知声明。未呈交的污染观察没有新视觉判断，其诊断只能由固定恢复规则及已审干净来源承担。

## 最后构建与交付

完成候选搜索、替换尝试、必要补采和原生审阅后再调用 `build-decision`。标题、速度、拍号、行外符号、首尾及打印边界由 Agent 确认。几何身份确认后，混合 gap 使用完整几何验证和恢复证据链；普通行的严格纯白切带规则保留，没有歌曲颜色或 codec 例外。partial 必须显式逐项确认 false，仅保留几何。

构建器输出绑定精确决定的 `acceptance.json`、`continuity.json` 和 `audit.json`。混合决定保持 `visual_review=false`。导航历史 flag 保留；实际补采的新 PTS 和逐 gap 脚本证据可以承担恢复审计。随后走原 `submit`、`export`、`replay` 和逐页 `confirm-delivery`，重新核对全部来源和门禁。每条打印谱行仍来自一张完整原帧，只转灰度。

交付清单可能因保留全部比较和性能记录超过 1 MiB。`confirm-delivery` 仅对已经核对 SHA256、且与成功 export 登记完全一致的 manifest 使用 16 MiB 上限。外部决定、审核回执及其他默认 JSON 读取仍限 1 MiB，不压缩或删除失败比较来缩小清单。

本次真实验证仅限 BV1bD421u7vu。复用旧 full 原帧不等于新 URL 的独立端到端基准；宿主 Token 与实际呈交计量不可见时仍为 null。开发中断、失败操作和调试调用也不能省略为零成本。关闭开关并在新目录运行默认 full 即可回退，保留所有实验记录。
