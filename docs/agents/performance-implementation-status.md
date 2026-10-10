# 端到端性能实施状态，#43

## 2026-10-10 最新续跑与真实验收

集成代码为 `931b399`。#51 显式兼容软件已完成离线验证；#45 完整真实基线及 #51/#52 放行均未完成。两份新独立视觉审阅已保存实际等待结果，没有接受决定、PDF、replay 或交付确认。

按用户授权自动定位当前 WSL、`CODEX_HOME` 与 Windows 用户目录，核对 sessions、archived_sessions 的首行归属。当前权威来源为 `/mnt/c/Users/26960/.codex`，同一根线程有多份续跑文件。Windows 与 WSL 的候选来源没有合并。本轮必要的 SQLite 只读查询仅取当前根 ID 的允许元数据，两侧均未找到对应行，没有改数据库、认证或配置。调查见仓库外 `issue45-autodiscovery-20261010.json`、`issue45-sqlite-root-source-20261010.json`。

`931b399` 修复同一权威 home 内续跑文件被误判为歧义的问题。自动 turn 选择按实际时间；同时刻不同 turn、首行归属冲突和根 session/parent 错绑均拒绝。事件去重复用原验证器。公共宿主计量测试 16 项通过，59.487 秒，Standards/Spec 各 0 finding。该变更没有重跑整个测试集；之前 163 项完整回归对应 `712437a`。

真实 CLI 已分别采集两个审阅线程的三个 root turn 分段。去重后观察到 45/43 次模型响应、43/41 次外层工具调用及 4,973,865/5,467,686 Token。这些数值包含各响应的重复输入、缓存输入和证据整理成本，来自并行且中断续跑的 review_only 窗口，不能作为串行性能配对。每个任务只导入末段 scope，前两段独立保存；末段重复导入后 host-usage.json hash 不变。所有 coverage 仍为 false，完整 `model_tokens=null`。缺失败调用、嵌套工具和实际图像呈交的闭合账本，不能将多个分段拼成完整生命周期。计量证据见 `/home/kenqia/issue-43-resume-notes/issue45-usage-partitions-20261010/real-partial-usage-summary.json`。

两份新审阅独立辨认 12 条空间行，并各补采一个新 PTS。第一份实际查看 49 原帧、49 完整原生细节，186 个经过几何校验的必需 pair 中 91 个 uncertain，实际 build/submit 均等待。第二份查看 49 原帧、48 原生细节，实际 submit 等待；草稿的只读内容诊断有 185 pair、92 uncertain，但未经完整几何资格校验，不能与第一份视为同等级验收。干净打印候选不能解除旧必需 pair 的移动光标污染。逐行来源草稿与完整结果在 `issue51-real-quality-20261010/new-independent-review-1/` 和 `new-independent-review-2/`，不是导出来源审核或 PDF 质量通过。

#52 的两份候选素材已匿名恢复，与旧 hash 精确一致；三份源重新计算 hash 均匹配。各候选首、中、尾图已实际查看，整曲质量尚未验收。三源冻结清单、PTS 和图像 hash 保存在 `/home/kenqia/issue-43-resume-notes/issue52-refrozen-sources-20261010/run-inputs.json`。没有展开 30 次成本配对，没有默认启用或远端写入。以下按日期保留此前实验记录。

2026-10-09，实施从 `3c460ec` 建立本地集成分支 `codex/issue-43-performance`。任务图来自 GitHub #44 至 #52，规格为 #43。原有 `.archify/`、`.scratch/` 和未跟踪规格文件保留。

## 依赖和放行条件

| 工单 | 依赖 | 工作 |
| --- | --- | --- |
| #44 | 无 | 生命周期计量 |
| #45 | #44 | 宿主真实成本与优化前基线 |
| #46 | #45 | 惰性原生证据 |
| #47 | #45 | 决定构建 |
| #48 | #46、#47 | 疑点审阅 |
| #49 | #47 | 内容冲突否决 |
| #50 | #46、#47 | 覆盖与行外审计 |
| #51 | #48、#49、#50 | 显式试验快路径 |
| #52 | #51 | 多视频配对验收与启用范围 |

#45 必须在改变正常审阅流程前建立新鲜真实基线。2026-10-09 用户确认允许 #46 至 #50 先在隔离分支进行软件实现与合成验证；这项顺序调整不免除 #45 的完整真实基线和各票真实质量验收。快路径只有在质量通过、真实端到端耗时与总 Token 均降低后，才能讨论默认启用。

## 2026-10-09 计量来源核查

本次会话可用工具没有直接提供覆盖所有 Agent 调用的 usage 接口。用户随后明确授权自动定位 Codex Desktop 会话目录，并只读采集真实 Token 与工具计量。采集仅保留会话标识、来源元数据和计量数值，不输出或复制对话、推理正文、工具参数、认证及敏感日志内容。

实际发现 `CODEX_HOME` 指向 Windows 的 `.codex`。通过当前会话 ID、项目 cwd 与 `originator=Codex Desktop` 匹配到 rollout；WSL 候选路径解析为相同文件且 inode 一致，未合并两份计量，也无需查询 SQLite。该记录包含逐响应 `token_usage_record` 的 `response_id` 与真实 `usage`，以及镜像的累计 `token_count`。二者不能重复累加。

实际数据源已可定位，#45 的采集、受控导入和汇总代码最初集成至 `782518b`，最终软件修复集成至 `d09fa9d`。每个真实视频的完整成本归属仍待验收。当前开发会话成本不等于视频基线；未知字段仍保留 `null`。#46 至 #50 按用户确认的隔离顺序进行软件研发，真实验收仍依赖 #45。#51 的显式兼容软件已获确认并进入隔离实现与审阅，#52 的真实放行仍未完成，不能声称性能目标达标。

标准真实样本为 `BV1rH4y1R7Rk`。本轮另匿名取得 `BV1zy4y127hV` 与 `BV1pu41127z3`，实际查看首、中、尾原帧，分别作为重复节奏与滚动接续、光标及固定界面覆盖的候选。后两类仍需完整视觉验收，三张预检不能证明整曲覆盖。

| 输入 | 时长秒 | 原生尺寸 | SHA-256 |
| --- | ---: | --- | --- |
| BV1rH4y1R7Rk | 298.6 | 1920×1080 | `80f9a8d19515cf624d7d13c27ea758e88118fddb4341fa06deaad040272877fe` |
| BV1zy4y127hV | 270.0 | 1920×1080 | `3891748105076ef2e3228e663bd3b0b179b1c4e9013a2d1b566432e0040de9b2` |
| BV1pu41127z3 | 268.366 | 1920×1080 | `1f96eb21aee577e01f00cc07e1b2da295e4d1e6329220e0ccaa982b69ea07afe` |

基准计划固定每个版本每样本五次、每次 1200 秒时限、nearest-rank 分位数，URL、本地同源与固定决定重放分组。计时配对组不并发运行。计划不是已完成的基准，仍需逐次保存完整成本与质量结果。

原版本标准 URL prepare 复测得到 48 张完整帧、770 张细节图和 25 张对照图，尚未包含审阅及导出。第一份真实独立审阅已导出 12 行、2 页，保存决定重放 PDF 字节一致，独立审计 8 个实际 PTS 和 13 个嵌入图块。实际呈交为 119 个观察包图像及两个 PDF 渲染页。该审阅与 prepare 属于不同采集范围，不能拼成完整端到端 Token 基线。

现有 JSONL 不能直接证明所有失败模型调用均有 usage，也没有全部图像呈交尺寸的宿主事件。只读检查 Windows 与 WSL 的 `state_5.sqlite` 后，两个数据库均无当前会话对应行，不能补齐这些缺口。不得把未找到记录解释为零消耗，或将已观察到的 Token 当作完整总成本。

上一轮第二次标准 URL prepare 和第二份独立审阅也已执行，审阅中发现并修订了第 68 小节上缘残留的前行符杆。两份判断分别为 12 行、2 页，逐份固定决定重放通过，独立判断的选帧与边界不同。尚未完成多视频配对基准或 #45 的完整验收。

此前恢复会话时发现 `/tmp/issue-43-context`、`/tmp/issue-43-benchmark` 和临时 worktree 已不存在。该次临时目录中的视频、决定、PDF 与原始验证报告不可复核，只保留会话记录，不能作为放行证据。新鲜实验已改用项目忽略目录 `work/performance-43-20261009/`，审阅报告保存到 `work/issue-43-context/`。历史文档中的 68/94 个图像 ID 不构成本轮基线。

## 已实现的前置工作

#44 的生命周期报告已本地集成，含只读 `report`、受控阶段事件、等待与失败成本、首次交付计时、重试和中断恢复。早期完整回归 94 项、生命周期专项 8 项通过。随后修复脚本导出提前停止交付计时、补采后旧呈交图像身份失效和内部计量事件缺字段未提前拒绝，并补强唯一图像身份统计。

冻结代码快照 `d09fa9dc55d0ce5d836492116498b9a8ed991a14` 的完整回归为 108 项、217.664 秒，全部通过。两轴最终审阅在已实施的 #44/#45 软件范围内没有剩余 finding。#44 本地验证完成，#45 软件完成，三类视频完整真实基线仍未验收。该次收尾时 #46 至 #52 尚未启动；后续隔离研发见文末。#43 未完成。最终证据与本次恢复核对见下文。

## 实施前验证

在原版本 `3c460ec` 运行仓库入口，88 项测试通过，耗时 200.863 秒。该记录是回归基准，不是视频提交到 PDF 的性能基线。

```sh
uv run --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt python -m unittest discover -s tests -v
```

## 远端状态

本轮只读 GitHub 工单，尚未 push、创建 PR、修改或关闭工单。远端写入仍需用户明确确认。#43 不能因本地完成一个前置票而标为完成。

## 恢复后的真实计量核验

新鲜第一轮标准 URL prepare 为 52.631 秒，第二轮为 51.976 秒，均不含审阅及 PDF 检查。两份源 hash、48 个实际 PTS、843 个图像 ID 与 hash 相同。双份审阅并发用于质量恢复验证，不能当作性能配对基线。

第一份新独立审阅已完成 12 行、2 页实际检查，保存决定的来源核验与 PDF 重放通过。公开 host CLI 按本次 child 线程与 root turn 的时间窗口采集并导入 59 个事件，其中 31 个模型响应、28 次可见宿主工具调用。实际观察 Token 为 5,036,868，其中输入 5,024,936、输出 11,932、缓存输入 4,800,000、推理输出 1,160。缓存及推理是拆分，不再加到总量。文字和图像 Token 拆分未知。重复导入输出一致，没有重复累计。

该范围含独立审阅与收尾，排除 prepare、获取和 root 开发。完整模型调用及失败覆盖、内部工具和图像计量仍不可证实，完整 model_tokens 保留 null。第一份 117 次实际图像呈交保存在独立记录，过去未采集的 timestamp/call_id 保留 null，不伪造为完整宿主事件。证据见忽略目录 `work/performance-43-20261009/standard-review-1/`，不得把这些 partial 数据当成 #45 完整基线。

## 最终证据与本次恢复核对

2026-10-09，本次恢复只核对项目 `work/` 中已保存的产物和报告，并运行公开只读 `report` smoke。没有重新下载视频、进行视觉审阅、重解码原帧或重复完整回归。此前临时目录丢失的记录仍不作为证据；下列证据来自其后保留在项目中的实验。

完整回归日志为 `work/issue-43-context/final-tests.log`，SHA-256 为 `7732cefe17c35bebaec1d7b1b3a2a0c7449ab448cc25e5a08aaa428d10ca54b5`。两轴报告为同目录 `review-spec-final.md` 与 `review-standards-final.md`，固定范围为 `3c460ec..d09fa9d`。无剩余 finding 只适用于已实施范围，不代表 #43 或 #45 全部验收。

两份真实质量审阅及各自保存决定重放的现存证据在 `work/performance-43-20261009/standard-review-1/` 与 `standard-review-2/`。本次核对 `checked-source-audit.json`、交付回执和产物 hash，结果如下。独立来源 PTS 数来自上一轮审计脚本的实际重解码，本次没有重跑该脚本。

| 核对项 | 第一份 | 第二份 |
| --- | ---: | ---: |
| 谱行 / A4 页 | 12 / 2 | 12 / 2 |
| PDF 嵌入图块 | 13 | 13 |
| 独立来源 PTS | 6 | 6 |
| 最低 effective DPI | 264.182 | 250.423 |
| export PDF 与各自 replay 字节相等 | 是 | 是 |
| export PDF、manifest 与交付回执 hash 相符 | 是 | 是 |

第一份 PDF SHA-256 为 `f8c9754273fe90af9d6691d532d479413676284f6075ab3e286ab16e31500723`，第二份为 `20bf4bf6fdb07d3d463095491fc1b9dcab2bf8fc0528255eea6cdcadf1712d5c`。两份独立判断的选帧与边界可不同，各自保存决定的重放必须字节一致。来源脚本明确不验证视觉内容；原有实际视觉判断和逐页交付回执另行保留。本次源完整性核对另保存在 `work/issue-43-resume-20261009/source-integrity.json`，两份 MP4 hash 与观察包记录一致，已保存的 48 帧实际 PTS 列表相同，没有新增解码。

新鲜公开 `report` smoke 两次均退出 0，所有任务 JSON 的 SHA-256 保持不变，当前交付确认有效。摘要保存在 `work/issue-43-resume-20261009/report-smoke-summary.json`，证据索引为同目录 `resume-evidence.json`。两份宿主成本均为 `review_only`，实际观察 Token 分别为 5,036,868 和 5,399,475。`model_tokens=null`；`lifecycle_complete`、`model_calls_complete`、`tools_complete`、`images_complete` 均为 false。这些数据不能补成完整端到端成本。

两份旧任务还均报告 `wall_clock_valid=false`、`wall_elapsed_seconds=null`。已有 prepare 事件中，第一份墙钟 58.896795 秒、单调时钟 56.974424 秒；第二份分别为 58.158619 和 56.198641 秒。报告记录 `wall_clock_discontinuity`，原因未知。本次不改账本，也不猜测根因；这些任务不能进入耗时基线。

只读 GitHub 核对确认 #44 至 #52 均为 open，#46/#47 的原生依赖仍为未关闭的 #45。没有修改远端状态，软件本地完成与远端工单关闭分别记录。

## 已确认的隔离研发顺序

2026-10-09，用户确认先在隔离分支推进 #46 至 #50 的软件实现与合成验证。稳定分支 `codex/issue-43-performance` 保留在 `39ce3ab`，其生产代码与冻结的 `d09fa9d` 相同。实验集成分支为 `codex/issue-43-software-experiment`，每票由独立 worktree 实现并合入该分支。

先并行实现 #46 惰性证据与 #47 决定构建；两项软件验证通过后再按原依赖实现 #48 疑点审阅、#49 内容冲突否决和 #50 覆盖审计。使用已确认的统一 CLI 与受控计量边界进行合成验证，保存红绿记录、完整回归与两轴审阅。原有全量路径继续可用，实验能力显式调用；不启用自动接受，不伪造实际视觉确认或真实模型成本。

#45 的完整真实基线及后续 #51、#52 门禁保持。GitHub 依赖、工单状态与远端分支不修改。实验阶段的合成验证和局部运行不能宣称真实视频质量验收完成或总耗时、Token 降低。旧任务不自动迁移，回退使用冻结提交与新结果目录，原决定和证据保持可追溯。

## 2026-10-10 隔离软件结果

#46 至 #50 的软件实现与合成验证已合入 `codex/issue-43-software-experiment`。最终代码和测试快照为 `6f344f0ddace1659788bd64f6a4d48161bf0112e`，工作目录为 `/home/kenqia/my_folder/issue-43-software-experiment`。默认仍为 full/prepare，没有自动接受；真实质量和性能放行尚未完成。

| 工单 | 本地实现 | 操作契约 |
| --- | --- | --- |
| #46 | 按需原生 ROI、缓存及可追溯观察更新，失败生成成本保留 | [惰性证据](lazy-evidence.md) |
| #47 | 当前包绑定、结构修正、确认、差异、来源和未决草稿，沿用现有决定协议 | [决定构建](decision-building.md) |
| #48 | 分类疑点、实际 PTS 上下文、ROI/有界补采请求；显式沿用未改的实际判断 | [疑点审阅](review-plan.md) |
| #49 | 对几何已提出的局部对应检查内容，冲突或不可靠证据等待 | [内容检查](content-checks.md) |
| #50 | v4 原生图块、逐项标题与行外审计、首尾/gap/段边界及精确决定文件绑定 | [覆盖审计](coverage-audit.md) |

最终仓库入口运行 150 项测试，403.639 秒，全部通过。日志为 `/home/kenqia/issue-43-resume-notes/final-verification-20261010/unittest-final.log`，SHA-256 为 `67b06176404710e41c72eb37b91a409a3217376f45b12a0f582679cdb62e5bba`。这是回归运行时间，不是视频端到端耗时。

离线 `ci/verify_agent_replay.py` 在生产快照 `2f9e231` 通过，后续至 `6f344f0` 仅修改性能测试，生产源码完全相同。固定决定输出 3 行、1 页，原生裁剪相等、重放 PDF 字节一致，最低 effective DPI 为 156.996，来源篡改、越界和未知版本均被拒绝。报告为 `/home/kenqia/issue-43-resume-notes/final-replay-reviewed-20261010/summary.json`，PDF SHA-256 为 `532b7cb98af23c0cc0b9fa10c0a04e459daf3686a2f9bc96de1c54a24f4b8f10`。重放不是独立视觉验收。

两轴审阅固定范围为 `39ce3ab...6f344f0`。初审各发现同一 P1，覆盖审计忽略实际 refinement 裁剪框。现已复用原生裁剪验证器返回的执行 bbox，row 和 extra 缩掉核查区域会等待，合法精修仍能导出与重放。最终 Standards、Spec 均无剩余 finding，报告保存在上述实验记录目录的 `review-standards-phase2-final.md` 与 `review-spec-phase2-final.md`。

中间 `2f9e231` 全套有一次 149 项运行中的计量测试错误，旧断言对允许为 null 的墙钟字段做加法。三次自然复测没有重现具体宿主异常，受控前跳则复现同一 TypeError。修复仅改变测试时间边界，正常时钟继续严格验证增长，新增前跳负例验证 null、具体异常、恢复保留及 report 不改账本。生产时钟门禁保持，原失败日志和诊断保存于 `final-verification-20261010/unittest-reviewed.log` 与 `review-fixes-clock/`。

污染必需对应的光标或遮挡仍不能仅靠补一张干净帧解除；所有必需对应必须具备可靠内容证据。导航限额只能按当前全部 gap 核查和真实新增 PTS 的有限入口解除，历史风险记录保留，`hidden_content_proven_absent=false`。这些支持限制没有被改成成功输出。

原工作区仍为 `39ce3ab`，原有未跟踪资产保留。七个已合入且干净的实现工作树已正常清理，分支和仓库外实验记录保留。没有新增生产依赖，三个 moving viewport 核心未改，防火墙通过。没有 push、PR、远端合并或工单修改；#45 的完整真实基线、各票真实验收及 #51/#52 仍待完成，#43 未完成。

## #45 配对入口测量，2026-10-10

使用同一份本地缓存的 `BV1rH4y1R7Rk-p1.mp4`，源 SHA-256 为 `80f9a8d19515cf624d7d13c27ea758e88118fddb4341fa06deaad040272877fe`，顺序运行冻结入口 `stable-39ce3ab` 的 `full/prepare` 与实验入口 `e35ae33` 的 `lazy/prepare`。两次都只到 `waiting`，没有提交视觉决定、PDF 或交付确认，因此这组数据只说明 prepare 层的观察生成差异。

| 入口 | 单调 prepare 秒 | 完整帧分析 | detail 图 | generated_images | 墙钟 | model_tokens |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| stable full | 41.460 | 48 | 770 | 843 | `null`，clock discontinuity | `null` |
| experiment lazy | 32.721 | 48 | 0 | 49 | `null`，clock discontinuity | `null` |

lazy 入口在这次相同输入上少生成 770 张 detail 图，少生成 794 张图像，单调 prepare 时间少 8.740 秒。这个差异不是端到端耗时或 Token 改善。两次均缺少完整模型调用、工具和图像呈交覆盖，也没有独立视觉审阅。配对原始报告、观察包和 `report` 输出保存在 `/home/kenqia/issue-43-resume-notes/issue45-baseline-20261010/paired-summary.json`。

当前仍不能完成 #45：完整生命周期需要统一入口获取、视觉审阅、补采/修订、PDF 检查和交付确认；当前宿主 JSONL 无法证明所有失败调用、嵌套工具和实际图像呈交。历史两份真实审阅各有 12 行、2 页和来源 replay，但都是 `review_only`，墙钟和完整 Token 为 `null`，不能与本次 prepare 结果拼成基线。

## #45/#51/#52 新核查，2026-10-10

用户确认继续完成真实基线和放行工作。本次核对当前 CLI 0.149.0 的 app-server 协议，并以只读代理检查快路径契约和最终验收准备。默认 daemon control socket 不存在；生成的协议提供线程/turn 用量、错误和工具 item，但不能证明逐失败模型调用、嵌套工具与实际图像呈交完整。没有启动服务、修改认证或配置，也没有调用新模型。能力字段与 hash 见 `/home/kenqia/issue-43-resume-notes/app-server-capability-20261010.json`，结论见同目录 `issue45-metering-capability-20261010.md`。

三个一秒本地时钟探针当前连续，不能修复旧任务账本或证明下一次完整运行有效。旧配对和 review_only 记录继续排除在完整基线外；真实 model_tokens 仍为 null，不将 coverage 改为 true。

预检发现汇总资格缺口：完整成本报告即使墙钟无效或耗时缺失，也能取得 `real_baseline_eligible=true`。本次最小修复要求每次运行明确有效且提供非 null 耗时，保留提交状态、完整及观察 Token 和原 null。公开 CLI 红绿验证覆盖合法正例和四个反例，完整宿主计量测试 10 项通过，26.115 秒。记录见 `/home/kenqia/issue-43-resume-notes/issue45-clock-gate-fix-20261010/`。此次没有重跑整个 150 项测试集，也没有进行新的真实视频基准；旧完整回归仍对应上文冻结快照。

#51 的现有校验要求每行实际视觉确认，不能直接填充脚本结果。具体兼容影响、有限范围和回滚入口见[最小兼容提案](fast-path-compatibility-proposal.md)。用户随后确认此提案，已实施的显式混合接受见[实验协议](script-acceptance.md)。自动接受范围尚无真实放行。详查记录为 `/home/kenqia/issue-43-resume-notes/issue51-contract-audit-20261010.md`。

#52 的逐项矩阵和串行采集计划见 `/home/kenqia/issue-43-resume-notes/issue52-preflight-20261010.md`。在已检索的两个项目 work 目录及 resume-notes 内，仅找到标准视频源；另两类候选需要恢复或重新冻结。一次入口组的三样本、两版本、每侧五次计划共需 30 个新鲜 review run，不能以保存决定 replay 代替。取得完整宿主来源并通过最小探针后，才展开真实配对。

#45 完整真实基线及 #51/#52 质量和性能放行仍未完成。未启用默认快路径，未 push、创建 PR 或修改工单。

## #51 显式混合接受实现，2026-10-10

用户确认兼容提案后，独立分支 `codex/issue51-acceptance` 完成首版软件，提交 `7186397`，合并最新授权记录后以 `19f28a7` 快进集成。只在新 `prepare --evidence-mode lazy --script-acceptance` 任务启用 `continuous_clean_v1`。默认 full、旧任务和旧决定不迁移，没有新增生产依赖或决定协议版本。

Agent 必须实际核查同帧完整原生 ROI 的 clean 状态，并确认首尾、标题、速度、拍号与行外区域。脚本重算全部五线、普通内部行 ownership band 和必需 gap，保留所有合理位移。脚本项记为 `script_acceptance`，混合决定的 `visual_review=false`；`acceptance.json` 精确绑定决定，submit/export/replay 均复验。有限像素规则不能证明任意小遮挡或擦线不存在，真实自动支持范围仍为空。

公开 CLI 专项 8 项通过，157.962 秒，涵盖混合提交、原裁剪、PDF 字节重放、缺 clean、未知遮挡、裁框外小符号、歧义位移、遗漏五线、gap、首尾及标题、精修缩框、旁记录和历史篡改、物化后显式修订。固定离线 CI 重放 passed，3 行、1 页，export/replay 字节一致；这不代表真实视觉或性能验收。

以 `a646a61...19f28a7` 进行 code-review 双轴审阅。Standards 发现 1 项 P2，ROI 五线复查混入完整帧分析计数。Spec 发现 1 项 P1，gap clean 只覆盖内容窗口，未覆盖旁记录声明的完整 band/ROI，合成 CLI 能错误成功。另有 sources.json 写入顺序造成返回与磁盘字段不同。全部由独立修复分支提交 `7449f2a` 修复后快进集成，Standards 与 Spec 最终复核各 0 项未解决发现。gap 反例保留 waiting，不产成功 PDF；ROI 复核单列次数、失败耗时与恢复；sources.json 与返回值一致。

实现代理因服务限流中断，`unittest-full.log` 无完整尾部，不计为完整回归。主 Agent 在同源码集成工作区重启统一 unittest，日志为 `unittest-integration.log`。初版 `19f28a7` 完整回归 159 项通过，668.409 秒。`7449f2a` 的完整回归保存在修复目录 `unittest-final.log`，中断未计为通过；最终 `712437a` 结果见下文。快路径专项 10 项通过，128.957 秒；性能专项 12 项通过，51.013 秒；最终固定 CI 重放 passed。原始证据和审阅报告保存在 `/home/kenqia/issue-43-resume-notes/issue51-implementation-20261010/`，修复红绿证据在 `/home/kenqia/issue-43-resume-notes/issue51-review-fix-20261010/`。

标准视频旧观察包的只读几何预检为 48 帧、47 个接续，其中 44 个有多个合理位移。这只是规划依据，不是新的真实双跑；不会用内容、颜色或最大重叠方案删掉其他合理位移。新鲜真实验证仍在软件回归后运行，等待和回退必须如实保留。

#45 完整真实成本账本缺口保持，#51/#52 尚未放行。没有默认启用、push、PR 或工单修改。本文按 unslop 自审。

`7449f2a` 将两份历史标准 full 任务复制到新目录后执行 replay，随后用当前独立验收脚本重解码核对原裁剪、灰度 PDF 嵌入像素、DPI、行序及分页。各 12 行、2 页，PDF 字节分别与保存 export 相同，原始任务全部 JSON hash 不变。新结果见 `/home/kenqia/issue-43-resume-notes/issue51-real-quality-20261010/historical-replay-summary.json`。这两份是保存决定执行，不属于新鲜视觉判断或真实成本配对，不能重复算为五次 review run。

## 真实 URL 等待路径与计划规模修复

`7449f2a` 通过统一 URL 入口新建两份标准 lazy/script 任务。两次取得同一源 hash `80f9a8d19515cf624d7d13c27ea758e88118fddb4341fa06deaad040272877fe`，48 帧、相同实际 PTS 与逐帧 hash，初始 49 张图、0 张 detail，完整帧分析各 48 次。prepare 的单调外部计时分别为 74.862、71.821 秒。这些运行与回归并行，只用于质量预检，不进入性能配对统计；完整 model_tokens=null。prepare 时墙钟有效，但没有交付终点，不能据此建立端到端基线。

新真实任务的 review-plan 首次返回 `sampling_budget`，因为缩进 JSON 为 1,173,688 字节，超出 1 MiB。`712437a` 将计划保存为紧凑 UTF-8 JSON，并按实际写入字节含末尾换行核对同一上限。其他 JSON 默认格式不变，不删字段或证据。修复后真实完整计划 644,614 字节，460 个疑点、48 帧及 163 份补采建议与修复前捕获的完整计划逐字段相同。受控 47 帧、5 行规模用例 RED→GREEN；紧凑仍超限的 9 行反例继续 waiting。review 专项 9 项、138.528 秒，workflow 6 项、41.347 秒，通过。该修复的 Standards/Spec 各 0 finding。证据在 `/home/kenqia/issue-43-resume-notes/issue51-plan-size-fix-20261010/`。

随后两份任务各物化完整同帧 ROI 48 张，观察版本 2，总图像 97 张，全部逐像素与当前原帧裁剪一致。重建计划各 637,858 字节，无剩余物化请求，460 个疑点仍保留，automatic_acceptance=false。仅实际查看第一任务首帧和第二任务末帧作为有限原生核查；没有填写全部 clean、身份或整曲确认，也没有保存决定、PDF 或交付回执。两份完整独立视觉判断、各自保存决定重放和 PDF 验收尚未完成。不可把两份历史决定重放替代这项工作。

新输入与实际 PTS 对照为 `/home/kenqia/issue-43-resume-notes/issue51-real-quality-20261010/new-url-input-comparison.json`，原生物化核对为同目录 `materialization-comparison.json`，实际有限查看记录为 `limited-native-inspection.json`。这些字段不是完整宿主图像呈交事件，真实事件账本缺口保持。

`7449f2a` 的完整回归第二次执行因工具状态恢复后进程消失且没有完成尾部，未认定通过。最终源码 `712437a` 使用带退出结果的 wrapper 重跑统一入口，日志为 `/home/kenqia/issue-43-resume-notes/issue51-review-fix-20261010/unittest-final-complete.log`，最终 163 项通过，745.659 秒，退出码 0；wrapper 单调耗时 746.506 秒。日志 SHA-256 为 `3ef1f1198cd7b6d5030b4c58ea3d2cd1d1bb950a24bc8b24a0d373be26469bed`，退出记录 `unittest-final-exit.json`。所有中断日志保留。

最终代码 `712437a` 完整回归 163 项通过，固定离线 CI 重放再次 passed，Standards/Spec 对兼容软件与规模修复各 0 项未解决发现。实验记录索引为 `/home/kenqia/issue-43-resume-notes/issue51-evidence-index-20261010.json`。本次收尾只完成 #51 显式隔离兼容软件；#45 完整真实基线、#51 真实支持范围及两份新完整视觉决定、#52 三类视频完整配对与耗时/Token 放行均未完成。缺完整宿主账本时保持总 Token 未知，无法取得真实自动支持范围。没有默认启用或远端工单状态变更。
