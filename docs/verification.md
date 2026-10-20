# 验证记录

## 2026-10-20 连续谱面分页修复

基于main的c3afed0，修复逐行切片后额外行距改变渐强、圆圈、重音关联位置的问题。原图路线每页一块连续条带，保持原行距；layout新增源长图hash绑定的page_breaks，实际查看分页接缝，有疑问整组保留并允许留白或多页。旧逐行原图PDF保留，新导出重新审阅，其他路线与未知调用恢复保持。

最终完整回归179项、172.745秒，其中177项通过，2项Windows专属测试在WSL跳过，无失败。使用下方当前PDF完整入口并增加`--python 3.12 --quiet`。长图专项13项、32.037秒，公开共同约束17项、35.405秒通过；源修复切口过期增量专项通过。新增实际PDF渲染的浅灰底连续性、已知分离记号与五线距离检查，以及连续覆盖、旧版升级和切口拒绝矩阵。两轴只读审阅0项发现；运行代码Ruff E701/E702/F821、compileall、references同步及本地链接检查通过，无静态类型检查配置。

用户《鲜花（Live）》保存材料在独立副本重排为4页，实际查看全部4页和3处分界两侧，48–49上方渐强及圈、后段重音恢复长截图中的原始相对距离，逐行白色间距消失。当前输出已按实际看图提交review-pdf；原任务record和原PDF未改。这是保存长图的新排版与实际页面审阅，没有新视频采集、模型调用、逐符号校对或Windows原生验收。证据见工作区`work/engineering/row-boundary-design/evidence/`和[实施记录](experiments/2026-10-20-continuous-page-boundaries.md)。

## 2026-10-20 默认原图直排

从main的`84d9062158f7f5b45e0078443d73c4fef2cebfbc`实施新任务默认原图直排，完整谱行或连续行组等比分页；可选局部去水印、真实原帧局部修复及显式重绘/矢量保留。安装Skill未更新。

最终完整回归176项、153.818秒，其中174项通过，2项Windows专属测试在WSL跳过，无失败。命令使用下方当前PDF完整入口，并在uv run后加入`--python 3.12 --quiet`。长图专项11项、公开共同约束最终16项、路线修复专项5项通过。完整回归包含仓库外自包含包的新任务原图及旧手动矢量合成重放。运行代码与CI重放脚本Ruff E701/E702/F821、compileall、references同步检查通过，无静态类型检查配置。

合成测试从PDF提取嵌入位图，与源长图对应区域逐像素核对；只证明嵌入未新增重采样，不证明音乐内容或长图拼接正确。清理测试核对原图及区域外像素，修复测试核对实际原帧、PTS/time_base、来源hash和重新审阅。新公开操作加入CLI、workflow和所属模块共同约束；原图导出复用完整布局、输出版本及全部预览拒绝矩阵。

规范轴最终0项发现；规格轴初审2项路线恢复问题均已修复并复核关闭。证据位于工作区`work/engineering/direct-source-implementation/evidence/`，详细方法见[实施记录](experiments/2026-10-20-direct-source-pdf.md)。本轮没有新真实视频、宿主生图、真实PDF视觉或Windows原生验收，合成及受控审阅不替代用户实际验收；没有安装更新或远端写入。

## 2026-10-20 长截图主线

从 main 的 `13f1dde` 在独立分支 `codex/longshot-main` 实施下载、自动长截图、一次整体审阅、宿主生图优先或矢量兜底及A4排版。局部符号允许推测并统一披露，新任务无需逐行填写来源。

最终完整离线回归166项、116.918秒，无失败；其中2项Windows专属测试在WSL跳过。运行命令为下方当前PDF完整入口，在 uv run 后加入 `--offline`，日志位于工作区 `work/longshot-smoke/full-final.log`。公开CLI新增覆盖连续滚动、空白片尾、浅色短五线、整体审阅、未知生成调用恢复、一次修正和去掉蓝标后连续行组自然分开。失败重拼仍累计解码预算，并保留之前有效材料。

实际查看《山海》1920×8731长图、原生首尾及最终四页A4矢量PDF，review-pdf后stage=complete。此次重新拼接解码约10.26秒，最后导出含预览约2.15秒，不含诊断、下载和人工查看。当前宿主没有生图工具，真实生图未验证；《空空》视频未找到。受控回填不作为实际模型生成证据。

标准独立审阅发现1项连续行组误判，修复后复核通过；规格审阅无实质偏差。Ruff E701/E702/F821、compileall、references同步及diff检查通过，无静态类型检查配置。未更新安装Skill，未push或合并main。详细证据与限制见[实施实验记录](experiments/2026-10-20-longshot-main.md)。

## 2026-10-20 main 合并验证

用户确认将 PDF 清理分支合入 main、更新本地 Skill 并推送。合并基于 main `40435091ee16eab4f1e814e8e47fec142bd0969e` 与清理提交 `4fa1a6066fae03241715f15b837070e019be2d2e`，保留媒体安全备份回退修复。唯一冲突为本页双方在顶部追加的验证记录，已完整保留；运行代码无冲突。

合并后的代码使用当前 PDF 完整入口重新回归：157 项、103.095 秒，其中 155 项通过，2 项 Windows 专属测试在 WSL 跳过，无失败。运行模块 Ruff E701/E702/F821、compileall、Skill references 同步及暂存 diff 检查通过。完整回归包含仓库外自包含包合成 PDF 重放、公开获取共同矩阵和媒体备份拒绝/回退测试。合成及受控回执不代表新真实视频、宿主生图或实际终稿页面验收。日志位于本轮聊天 outputs/main-merge-regression.log。

## 2026-10-20 PDF Skill 清理

从 `332922000d088803f4d74e8d7a4a7ebf93f26fc8` 建立隔离工作区，按用户确认删除 sparse/strict、MIDI、专属测试和运行协议，并移除 RapidOCR。运行包从 32 个文件减为 18 个，Python 模块从 20 个减为 12 个。来源审阅保留一份具体说明，宿主生图优先和矢量回退保持。

完整离线回归 150 项、595.034 秒通过，2 项 Windows 专属测试在 WSL 跳过。该轮启动后另收紧局部改源的显式批准，并删除无用连续解码方法与缓存扫描统计；最终版本新鲜增量验证为来源审阅 9 项、单帧宿主兼容 4 项、原生缓存 7 项，全部通过。公开入口删除拒绝与 Windows UTF-8 BOM 请求已包含在完整回归内。

独立只读审阅复现的局部批准继承问题已修复并补回归；生图回填文档已补充固定 `tool="host-imagegen"`。运行模块 Ruff E701/E702/F821、compileall、references 同步、Skill quick_validate 与 diff 检查通过。扩大到旧测试文件的风格扫描仍有原有 E701/E702，未把这些无关格式改动混入本次清理；现有 CI 的运行代码检查通过。没有配置或宣称静态类型检查。

现有 CI 合成重放通过：三行谱面导出一页 A4 矢量 PDF、嵌入位图为 0、独立双跑字节一致；损坏图片、越界、未知版本与来源未决四类拒绝通过。

验证材料为合成视频、受控宿主回执与程序拒绝测试；没有新真实视频、宿主生图或实际终稿看图验收，不据此宣称不同模型成品质量相同。旧扫描任务使用保留旧版，不自动迁成新版来源批准。

## 2026-10-20 不安全媒体主地址的备份回退

基线为已安装 Skill 对应提交 `332922000d088803f4d74e8d7a4a7ebf93f26fc8`，本地实施分支为 `codex/media-backup-fix`。主地址使用 HTTPS 8082 时，安全检查原本会直接终止，无法尝试同流备份。现在只对媒体候选中的 `unsafe_media_target` 继续已有的有界回退，每个候选仍独立校验。大小、分辨率和公开 API 路线的完整时长不符仍立即停止。

离线回归先复现失败，再验证普通路线与公开 API 路线跳过不安全主地址和首个备份、私有 DNS 不连接、全部地址不安全时拒绝、备份不可解码及大小/分辨率/时长保护。公开获取共同矩阵的 CLI、workflow、acquire 三个入口使用真实 HTTP 解析与合成媒体，验证公开 API 提取的官方备份可恢复，签名标记不出现在回执中。

针对性 `test_media_backups.py` 5 项和 `test_api_acquisition.py` 8 项通过。使用本页完整回归命令，加 `--python 3.12 --quiet`，241 项耗时 574.125 秒，无失败；其中 239 项通过，2 项 Windows 专用安装测试在 WSL 跳过。compileall、Skill references `--check` 与 `git diff --check` 通过。原始日志保存在本工作区 `work/media-backup-fix/`，包含修复前失败与修复后结果。

离线验证阶段没有访问用户提供的视频、真实下载、生成 PDF、生图或逐页验收，也未更新已安装 Skill、提交或远端写入。离线通过不证明该视频当前可以下载。后续真实验收应在独立任务目录运行公开 prepare，核对 `origin.backup_used`、实际分辨率及来源文件；该步骤本轮未执行。

## 2026-10-17 接续判断集中与冗余清理

main `9e54276` 起点上集中共享几何、编号与接续证据；冻结不再导入导航，判定阈值、策略版本、blocked 条件及证据格式保留。清理四个无用导入、一个无用赋值和一个不可达条件项。新增冻结独立重检及同号内容变化拒绝反例。

完整带 Mido 回归194项296.440秒，无失败或跳过。Ruff E701/E702/F821、compileall、references同步与diff检查通过；未配置静态类型检查。Standards与Spec独立审阅均无阻塞发现。首轮迁移漏导入导致的失败已修复，日志保留。

KiLLKiSS、标准曲、小星星及鲜花保存材料共26张原生截图、22组相邻比较，基线与修改后的全部检测及比较结果相同，原任务记录hash不变。鲜花原未决状态保留。没有新视频采集、宿主生图、全曲来源批准或PDF页面验收。命令、实际PTS与hash、限制及本机日志见[接续规则集中验证](experiments/2026-10-17-continuity-refactor/README.md)。

## 2026-10-17 行首小节号与导航修复

基线 `bd3b86d3133b1c5f05ac90474bd467768865183b` 上新增行首小节号优先锚点、缺号暂停及 Agent 来源绑定恢复；修复跨行光标、未知新增量、横线与括号归属、疑点影响范围、稳定原始问题及两次无收益停止。RapidOCR 1.4.4 运行依赖经本地验证及用户明确批准。

完整带 Mido 回归192项、245.087秒，无失败、无跳过，命令使用本页完整入口。新增13项针对性反例，公开入口共同约束覆盖 CLI 和 workflow 的 review-row-anchors。首轮全回归发现字符串未决兼容和旧无号测试假设，修复后重跑通过。compileall、Ruff 0.14.14 E701/E702、Skill references 同步和 diff 检查通过；未配置静态类型检查。Standards 与 Spec 独立审阅的两项恢复发现均修复关闭，增量兼容修正也已复核。

原10.48/23.08秒三行全部匹配，compare 返回 new_complete_rows=0，原 `[722,1061,1078]` 已区分括号和底部残缺组。新鲜花迭代开发任务保留10张，8次向前、2次端点、0次回查、0次局部扫描，7条跨度调整不另计截图；172.32秒因同号原生内容未证明一致暂停，尚未完成真实全曲导航验收。无新生图或PDF，未推送或安装宿主。证据和限制见[导航修复实验](experiments/2026-10-17-navigation-repairs/README.md)。

## 2026-10-17 稀疏导航与谱行清单

分支 `codex/sparse-row-navigation` 从 main `7590af9` 实施。完整带 Mido 回归 179 项、167.647 秒，无失败、无跳过；compileall、Ruff 0.14.14 E701/E702、Skill references 同步和 diff 检查通过。未配置静态类型检查。Standards 与 Spec 独立审阅发现的问题已修复，复核均无剩余发现。

默认 stage 改为首尾布局检查及自适应谱行跳转，显式 strict 保留连续扫描，新增持久 row_manifest 和实际编号接续入口。十四项导航反例及公共契约覆盖恢复、稳定身份、不同位置重复音乐、矛盾编号拒绝、严格扫描新增观察的资格撤回、原生微小差异与 1×1 header。

真实鲜花新任务到达335.28秒，保留150张、局部连续68帧；程序来源仍blocked，Agent实际核对后通过公开操作恢复标题及27完整谱行、印刷小节1–113，裁剪检查通过，ready_to_redraw。严格全曲覆盖false，没有新生图或PDF验收。旧main首轮overview为128张、1590帧、到63.56秒；不同覆盖范围不证明速度或截图数量提升。实测、失败恢复、原生PTS、导航日志和对比见[本轮实验记录](experiments/2026-10-17-sparse-navigation.md)。

## 公开入口共同约束

宿主检查矩阵为 CLI 和 `host_check.check`，由 `tests/test_host_check.py` 验证版本边界；`tests/test_public_contracts.py` 同步导出该矩阵。CI 的所有解释器声明须符合此支持范围。

`tests/test_public_contracts.py` 注册获取矩阵 CLI、`score_workflow.prepare` 与 `public_video.acquire`；`tests/test_api_acquisition.py` 对三者共用真实 HTTP 解析、代理拒绝和媒体 fixture，检查 API 恢复、来源身份与脱敏。

`tests/test_public_contracts.py` 用现有 unittest 的 `subTest` 注册入口矩阵。导出覆盖 CLI `export`、`score_workflow.export` 和 `reconstruction.export_vector`；审阅覆盖 CLI 与三个公开 module；分组覆盖 CLI、工作流与任务 module。新增同类公开入口时加入对应矩阵，不另建测试框架。

裁剪与批量请求生命周期的 CLI/module 入口也注册共同矩阵；已删除路线由 CLI 拒绝测试覆盖，损坏来源仍由正常 load 拒绝。

矩阵检查布局和有序全部预览、缺失或过期审核版本、相同 PDF 字节的新版本、缺页、缺报告、损坏预览，以及默认和显式分组的行数与可读性限制。历史身份恢复继续由 `test_stage_cli.py` 验证。审阅时核对入口是否注册、共同约束是否适用于该入口；确定性的拒绝行为由 CI 验证。

获取期限测试使用真实父进程、工作进程和 OS 信号。复制测试只替换离线下载 fixture，在复制开始时发送就绪事件；父进程仍使用生产总期限并终止工作进程，断言发布暂存清理和进程退出。其他生命周期案例保留 DNS、提取、下载、probe 与退出阶段。启动等待与操作取消分别验证，不修改生产期限。

完整回归和期限测试期间避免在同一机器并发运行真实 FFmpeg 解码或 Poppler 批量预览。现有 CI 分片顺序执行测试。安装验证使用提交快照的全文件 hash、入口检查和合成集成 smoke；修改代码仍需在 WSL 原生目录完成全回归。

## 2026-10-16 五项使用反馈修复

完整带 Mido 回归 161 项、139.880 秒、无跳过，全部通过。使用本页完整回归命令，并增加 `uv run --quiet` 减少解析输出。Ruff 0.14.14 的 E701/E702 检查覆盖扫描、任务、工作流、CLI 和宿主检查模块；compileall 与 `git diff --check` 通过。仓库未配置静态类型检查，compileall 不等同于类型检查。两轴独立审阅各发现一项，修复无界 mask 缓存及恰好触边漏检后复核通过。

真实来源仅重跑 BV1Yw4m1Y7YH 的前 10 秒，250 帧候选从 210 张降至 37 张，字节从 61,370,224 降至 11,210,193，单次墙钟从 34.971 秒降至 7.024 秒。标准曲与小星星历史材料只读裁剪检查通过；鲜花区域 24、25 触边，实际查看原图后保留 blocked，未修改历史产物。没有新的整曲扫描、真实生图或全部 PDF 页验收。测试、测量方法与限制见[本轮实验记录](experiments/2026-10-16-retro-five.md)。

## #61 本地集成验收

2026-10-14，#62、#63、#64 及双轴审阅修复合入 `codex/issue-61-integration`。最终代码提交 `94708a6` 的完整带 Mido 回归为138项、138.441秒，全部通过；合入提交 `b00fa5b` 的代码树与该测试版本一致。compileall、diff 检查和仓库外公开 CLI help smoke 通过。新测试验证强制独立导出版本审阅、相同 PDF 字节的新版本拒绝旧请求、两条公开导出路线的共同布局/全部预览资格，以及显式生图分组的有效符号分辨率。

两轴初审共4项发现，重叠问题集中修复：旧请求缺版本可批准新输出、本地矢量出口缺布局和预览检查、显式分组绕过可读性限制。终稿请求现在必须提交实际查看的 UUID `output_revision`，内容 hash 只用于产物完整性。旧审核经公开 stage/export 升级为待审输出，旧文件和调用额度保留。复核结论另行记录。

Root 通过公开操作对三曲四路线历史材料重新排版，并实际查看全部13页。审阅修复后再次公开升级四个输出，重新查看全部13页，以新 UUID 审核后 stage 均返回 complete。有序预览 hash 与升级前一致，历史调用和修正额度未变，强制矢量 PDF 没有嵌入位图。布局 minimum_gap=40、目标1页时，标准曲2页、小星星1页、KiLLKiSS生图及矢量各5页；无法达到目标时保留完整行和自然比例并解释。

这些结果是保存材料的确定性重放及新终稿页面实际审阅，没有新宿主生图或新的整曲来源批准。独立真实标准曲的新扫描及 stage 继续在原生单像素疑点处 blocked。未知模型成本 null。完整日志、全部页回执和原始失败记录保存在 `/home/kenqia/issue61-context/`，详见 `review61-fixes-notes.md`、`replay64-root-review.md` 和 `real64-stage-blocked.json`。未执行远端 CI、push、PR、Issue关闭或main合并。

新版默认入口使用截图粗拼、宿主生图优先、轮廓矢量兜底与完整谱行 A4 重排。#58 在用户明确调整的验收要求下通过，#59 删除旧编排并切换入口。可靠整曲 MIDI 的原严格准确性门槛仍未通过，历史失败没有改写为成功。

## 离线验证

2026-10-14，#63 实施分支完整带 Mido 回归为 122 项、100.064 秒，全部通过，compileall 与 diff 检查通过。新鲜真实标准曲连续观察 8958 帧，自动选择一个标题块和十二条完整谱行；原生单像素变化保留未决，结果为 `blocked`。Root 实际查看完整粗拼，没有批准生图或最终交付。命令、覆盖范围与真实限制见 [#63 自动来源检查记录](experiments/issue-63-automatic-source-checks.md)。

2026-10-14，#62 实施分支的完整带 Mido 回归为 99 项、56.478 秒，全部通过。新增统一 CLI 合成验证覆盖缓存晋升零重复解码、缩略尺寸改变、恢复、容量淘汰、候选损坏与缺失、来源改变、独立生图分组及小符号有效分辨率、未知调用恢复、一次修正与混合谱行材料。公开工作流另验证来源审阅撤回后禁止调用，以及截图发布中断后的恢复。受控生成回执只验证协议与预算；没有新的宿主生成或音乐视觉判断。日志保存在本机 `/home/kenqia/issue61-context/ticket62-final-all.log`，集成分支需另行回归。

当前 PDF 完整回归入口如下。上文旧版本的带 Mido 结果保留为历史记录；新版已移除 MIDI 入口及专属测试。

```sh
uv run --python 3.12 --quiet --isolated --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt \
  python -m unittest discover -s tests -v
```

新测试保留匿名网络、真实工作进程与信号期限、分 P、公共 DNS/TLS、签名 URL 脱敏、配置与认证哨兵、资源大小、原媒体尺寸、跨文件系统独占发布、用户目录保护、实际 PTS 和临时解码清理。默认入口检查新版任务、旧任务拒绝、恢复与 PDF-only 无 MIDI。重绘测试覆盖来源损坏、完整性、重叠与重复音乐、原生输出比例、一次修正、预算恢复、矢量路由、失败选择原子发布和最终 PDF 验证。MIDI 检查完整播放顺序、精确事件、读回、用户近似授权及路径边界。

当前 CI 使用合成视频和保存的确定性选择检查矢量 PDF、A4 与来源拒绝。它不调用宿主模型，不提供真实视觉或音乐准确证据。#59 实施 worktree 完整87项、43.578秒通过，日志 `/home/kenqia/issue54-recovery-evidence/issue59-full-final2.log`，包含可选 Mido。Python compileall、diff 检查和仓库外新版 help smoke 通过。最终 integration 冻结回归结果另行追加，实施 worktree 验证不冒充远端 CI。

## 三视频真实验收

用户要求修复 KiLLKiSS 第31小节遮挡后重新验收强制矢量 PDF，并接受“劣质一点也无所谓，能跑就行”的完整近似 MIDI。[验收调整](agents/reconstruction-acceptance-amendment.md)记录授权原话、产物和门槛。

三曲新鲜 PDF 为 KiLLKiSS BV15crrYUEPA、标准 BV1rH4y1R7Rk 与另一作者“小星星”BV1np421S78S，均保存来源、实际 PTS、完整谱行、宿主调用与每页实际审阅。标准和小星星分别两页、一页，KiLLKiSS 生图及强制矢量各三页。第31小节使用78秒实际PTS1248000的新完整原行修复装饰音遮挡；root 独立查看两路线全部六页和12张关键细节。矢量无位图，固定决定重放保持相同 PDF hash。

三曲近似 MIDI 由 root 独立 Mido 回读：小星星107事件、120拍、57600ticks；标准594事件、352拍、168960ticks；KiLLKiSS1409事件、540拍、259200ticks。均480PPQ、GM第10通道，完整曲长与 note-on/off 配对检查通过。输出标记 `midi_playable`、`reliable=false`，作者鼓件映射、节奏近似和播放约定如实保留。能解析和曲长正确不证明作者音乐等价。

实际记录见 docs/experiments/issue-58-standard-pdf.md、issue-58-other-pdf.md、issue-58-killkiss-independent-review.json 与 issue-58-playable-midi/summary.json。持久任务在 experiments/2026-10-13-issue58-recovered/。这些绝对任务位置只在本机可用，真实生图和每页看图不能用受控测试替代。未知模型成本为 null。

## 历史记录和限制

旧232项回归和2026-10-12首发10视频批次属于旧代码版本，结果通过 Git history 及保留的 release-test/data 查看。不能与新版测试数量合并。更早 /tmp 现场在环境重置后丢失，已保存档案仅证明历史产物，不宣称恢复或新看图。

当前只有 Codex 真实整曲记录，其他宿主没有整曲验收。仓库 Skill/CI 修改不代表宿主安装更新或远端 CI 通过。发布、工单关闭与 main 合并分别按用户授权执行。

## 最终集成结果

冻结提交 `c78bf48236a5127405ca36ed51e80755d246c4dd` 的完整带 Mido 回归为87项、34.875秒、无跳过，全部通过。两轴独立审阅无剩余发现。正式 CLI 重放三曲和强制矢量任务保留已验收 PDF，MIDI 恢复保留原记录；本次没有新的生图或视觉判断。独立 CI 合成矢量双跑相同，并通过四类拒绝检查。记录见 [#59 最终证据](experiments/issue-59-final/README.md)。

## 2026-10-14 任务规则集中验证

`score_task.py` 集中两个现有入口的选行、重绘失效、修正预算、恢复与记录发布。针对性测试新增两个跨入口反例：本地入口拒绝损坏的导航图和生成图；同选择保留修正预算与已审核 PDF，改变选择同步清空当前重绘和 PDF 引用。中断测试在文件替换处注入失败，不再依赖跨文件私有保存函数。工作流18项、本地矢量12项通过；上面的完整带 Mido 命令为89项、27.755秒、无跳过，全部通过。

三曲的四个现有任务通过来源与全部引用校验：小星星1页、标准曲2页、KiLLKiSS生图与强制矢量各3页。原任务记录及缓存 PDF 未改变。在临时副本中通过两个入口重新确认相同选行，当前结果、调用次数和修正预算保留；再执行实际导出。基线 `582bd1b` 与新实现从同一副本路径导出的 PDF 字节一致，新导出的全部9页1400像素渲染与原 PDF 渲染逐文件一致。Agent 实际查看这9页，未见分页、裁断或重叠变化。

这是保存选择与生成材料的确定性重放，以及既有页面的重新查看；没有重新生图、重新判定整曲来源或逐符号音乐校对。临时验证目录为 `/tmp/score-task-real-qa-_oximiyl`，不是永久产物位置。跨目录位图 PDF 的原始 hash 不作为比较依据，因为 ReportLab 使用图片路径生成内部对象名；比较使用同路径基线 PDF 和实际页面渲染。

`python -m compileall -q skills/bilibili-drum-score-to-pdf/scripts tests`、`git diff --check` 与新版 CLI `--help` 通过。仓库没有静态类型检查配置，compileall 只证明语法可编译。标准与规格两轴独立审阅未发现需要修改的问题。

## 阶段入口与恢复

准备后使用 `stage` 自动推进至宿主调用或实际审阅；局部来源版本、输入额度恢复、打印布局和全部页面预览见[阶段入口、局部恢复与打印布局](agents/stage-recovery-layout.md)。`layout` 修改边距、最小行距和目标页数，复用已接受生成结果；最终审阅必须显式绑定当前导出回执的独立 `output_revision`，PDF hash 只用于产物完整性。程序检查与实际看图分别记录。

`tests/test_stage_cli.py` 使用统一 CLI 验证 A→B→A、未知调用不重发、耗尽后真正新输入、精确重新分组恢复、接受结果插行后重映射、布局复用、全部预览与标准合成视频阶段推进。必要公开工作流异常测试验证选行发布中断与 Poppler 失败保留上个有效状态。测试中的回执和审阅备注均为受控证据；没有新真实宿主生图，也不代表真实来源完成音乐校对。真实来源单像素未决仍保留 blocked，不能以合成测试通过解除。


2026-10-14，#64 集成提交 `1b0eb04` 的完整带 Mido 回归为 131 项，全部通过。Root 在任务副本中公开重放三曲四路线，实际查看全部 13 页，标准曲 2 页、小星星 1 页、KiLLKiSS 生图和强制矢量各 5 页。调用与修正额度保留，强制矢量没有嵌入位图。该记录来自 `/home/kenqia/issue61-context/replay64-root-review.md`，属于历史材料重放和本次页面查看，没有新宿主生图或新的整曲来源批准，未知成本为 null。标准曲独立来源的单像素变化在公开 `stage` 中仍为 blocked，回执保存在 `/home/kenqia/issue61-context/real64-stage-blocked.json`。

最终审阅修复覆盖省略版本、旧版本与同 PDF 字节的新版本拒绝，旧 hash 审核升级为待审输出，公开矢量导出的布局与全部预览资格，以及显式新生图组和单行可读性限制。历史超过八条谱行的相同接受身份恢复保留已用修正额度。测试中的模拟历史记录和图像仍是受控离线证据。


审阅修复后，Root 通过公开 `stage` 将四路线旧 hash 审核输出升级为独立 UUID 版本，实际重新查看当前全部 13 页，并用各回执的 `output_revision` 提交 `review-pdf`。四路线随后均返回 complete，预览 hash 与升级前相同，原 PDF、调用和修正额度保留。摘要与升级请求保存在 `/home/kenqia/issue61-context/replay64-final/`。这次重新审核只批准当前打印版本，来源仍沿用历史证据，没有新生图或新的整曲来源批准。


最终审阅修复工作树完整带 Mido 回归为 138 项、138.441 秒，全部通过，日志 `/home/kenqia/issue61-context/review61-fixes-full-final-retry.log`。首次完整回归发现一个旧测试仍传 PDF hash，更新为对应导出回执后，第二次回归遇到未修改的复制期限 fixture 在固定 2 秒内未到复制标记。该 fixture 独立复跑通过，停止预览并发后完整回归通过，没有放宽期限或修改生命周期测试。`compileall` 与 `git diff --check` 通过，失败日志保留。

## 2026-10-15 自包含 Skill 分发

对外目录 `skills/bilibili-drum-score-to-pdf/` 现在携带 SKILL.md、脚本、references 和 MIT 许可证。协议从仓库 docs/agents 生成，并由测试检查同步及包内链接。只有被选择的 Skill 与视频链接时按默认 PDF 流程执行，README 区分首次安装、显式调用、宿主发现检查与开发者入口。

本分支完整带 Mido 回归为149项、112.943秒，全部通过。新增安装测试验证提交快照、重复安装、损坏拒绝、链接拒绝、任务保留、失败恢复与回滚；包测试将整个 Skill 目录复制到仓库外，从该目录的脚本执行 CLI 帮助和已有合成 PDF 双跑及拒绝用例。脚本实际导入位置被检查，测试目录没有源码仓库的 docs 或 skills 层级。

这证明分发目录在文件与协议层面自包含，不证明新的宿主界面已发现它，也不代表真实视频、模型调用或音乐准确性已验收。原有来源未决状态保持。原生转换实现和网络保护没有修改。完整日志保存在本工作树 work/evidence/full-regression.log。

## 2026-10-15 retro 环境改进

新增公开入口共同约束矩阵和安装工具测试；修正复制期限 fixture 的阶段同步，保留生产总期限、真实 OS 取消和清理断言。最终完整带 Mido 回归为 148 项、138.912 秒，全部通过，日志 `/home/kenqia/issue61-context/retro-full-final.log`。前一版 146 项回归为 130.888 秒，新增恢复边界测试后重新运行完整验证。`compileall` 和 `git diff --check` 通过。

AGENTS 与 Skill 正常流程指向 stage 文档，异常恢复按条件加载；工程交接分离当前事实和历史事件。安装工具从指定 Git 提交发布完整快照，保留备份和未管理任务；旧重复 Skill 布局可升级。发布异常与恢复异常分别测试，恢复失败保留含任务的暂存目录。自动发现将新矩阵和安装测试纳入已有 CI；本条记录是本地验证，不代表新远端 CI 结果。

本轮没有改动音乐采集、识别、排版或模型调用行为，也没有新的真实来源判断或页面审核。真实标准曲的原生单像素未决继续保留 blocked，合成 fixture 不解除该状态。


## 2026-10-16 main 整合验证

在独立工作区将 `codex/retro-environment-fixes` 合入远端 `main` 的 `68b53c8`。保留自包含 Skill 分发、便携 references 与安装恢复保护，合入五项反馈修复、交接规则和共同契约矩阵。`host_check` 同时支持包内 references 与旧仓库 docs；仓库外复制包测试覆盖发现与协议检查。

完整带 Mido 回归 164 项、137.268 秒、无跳过，全部通过。包测试单独运行 11 项通过。references 同步检查、Ruff E701/E702、compileall 和暂存 diff 检查通过；冲突解决经两轴独立复核，无新增发现。完整日志保存在原工作区 `work/retro-five/merge-full-suite.log`。本轮没有新视频、生图、页面验收或宿主安装更新；原工作区用户修改保持。

## 2026-10-19 匿名 API 恢复

完整带Mido回归202项、353.780秒，无失败或跳过；使用本页完整回归命令并增加 `--quiet`。新增获取矩阵覆盖CLI、工作流与acquire，检查CONNECT403/网页412的一次API直连恢复、分P、试看与实测时长、私有媒体DNS、脱敏和既有总期限。包内引用、compileall与diff检查通过；协议引用缩短后另跑包内协议及链接检查通过。

正式CLI在本地受控代理返回CONNECT403后，通过真实API和CDN取得鲜花及BV1yGGN6XE1B的完整1080p来源。用户另外回传豆包临时脚本下载鲜花成功；新通用版本尚未安装到豆包，尚无豆包完整PDF和逐页审阅证据。没有修改导航、裁剪、重绘或排版。首轮真实DNS失败保留，未添加DNS例外。详见[豆包诊断记录](experiments/2026-10-19-doubao-anonymous-acquisition.md)。

## 2026-10-19 CI 解释器兼容性

CI 四个任务曾因 Python 3.14 与固定 RapidOCR 1.4.4 的 Requires-Python 不兼容而在安装阶段失败，测试未执行。三个 job 定义现统一固定 Python 3.12；宿主检查的 CLI/module 同时验证 3.11、3.12、3.13 与3.14 的支持边界。

在仓库外 CPython 3.12.12 新虚拟环境中，标准 pip 安装所有固定依赖及可选 Mido 成功，pip check 无冲突，实际 host_check runtime_ready=true。完整回归204项、348.339秒，无失败或跳过；CI合成replay、原有Ruff E701/E702、compileall和包内引用同步检查通过。该结果属于本地验证，远端修复版本尚未执行。方法与日志见[CI版本修复记录](experiments/2026-10-19-ci-python312.md)。


## 2026-10-19 Agent-first 跨宿主修复

main 基线 `9cece50dcfe78affd6f8739c3221521d8bdbf55d` 上的实现工作树完整带 Mido 回归为 227 项、482.891 秒，无失败或跳过，全部通过。Agent 专项 15 项通过。新增覆盖默认 stage 无扫描、全部共享选源入口的新契约、合法旧任务局部升级、首尾角色变更拒绝、原疑点处理、局部额度恢复、无工具矢量路径、摘要与当前 PDF 版本绑定。显式 sparse/strict 原路线继续通过。

UTF-8/POSIX 安装、严格旧清单校验、失败恢复、混合缺号与残行、FFmpeg 两种能力路径以及不可读无关 Skill 的测试通过。references 同步、Ruff E701/E702/F821、compileall 和 diff 检查通过。标准与规格独立复核无剩余发现；原失败和修复过程见 [本轮实验记录](experiments/2026-10-19-agent-first-cross-host.md)。本地完整日志保存在工作区 `work/agent-first-cross-host/full-final.log`。

本机 Linux FFmpeg 4.4.2 的合成重放和有限时无网络解码探测通过，实际 PTS 为 0、time_base 为 [1,1000]。合成矢量 PDF 双跑字节相同，4 类拒绝检查通过。新版 fps_mode 参数路线由模拟能力矩阵验证。Windows 原生重点套件已加入 CI，尚无本轮远端运行结果。按用户确认，真实视频、实际看图与跨宿主验收由用户执行，步骤见 [Agent-first 用户验收清单](https://github.com/kenqia/bilibili-drum-score-to-pdf/blob/332922000d088803f4d74e8d7a4a7ebf93f26fc8/docs/agents/agent-first-cross-host-acceptance.md)。合成测试和受控 review 声明不证明真实音乐完整或模型实际看图。本轮没有新真实视频、生图、共享 Skill 安装或远端写入。


## 2026-10-19 Windows 安装路径修复

提交 `42c4288` 的 [首次 CI](https://github.com/kenqia/bilibili-drum-score-to-pdf/actions/runs/39273139112) 中，Linux 两个分片、MIDI 和合成重放通过；Windows 安装 10 项在路径校验入口失败。原因是 `Path.resolve()` 会展开正常的 8.3 短路径，旧检查将字符串形式变化误当作链接。

本机 Windows Python 3.12.1 已实际复现同一目录的短路径没有 symlink/junction、但旧安装器拒绝的情况。修复改为逐级检查真实链接，再规范化路径完成包含关系和备份身份校验。回滚兼容旧清单的大小写与短路径，仍拒绝其他目标的备份。

Windows 原生安装 12 项、15.926 秒全部通过，无跳过；Linux 安装 10 项通过，2 项 Windows 专属检查仅在 Linux 跳过。覆盖短路径安装、升级、旧清单回滚、任务保留和目录联接拒绝。提交链接测试通过 Git index 的真实 120000 类型构造快照，不需要改变 Windows 开发者模式或管理员权限。Ruff、compileall、引用同步和两轴复核通过。日志保存在工作区 `work/agent-first-cross-host/windows-repair/`；完整新版远端 CI 结果继续单独核对。

## 2026-10-19 Windows CI 原生工具安装

提交 `4954fcc` 的 [第二轮 CI](https://github.com/kenqia/bilibili-drum-score-to-pdf/actions/runs/39275775744) 中，Linux 两个分片、MIDI 和合成重放通过。Windows 安装测试 12 项通过，随后合成解码探测失败。Chocolatey 包源返回 503/504，报告安装零个包但退出码为 0，旧步骤错误地继续运行测试。

Windows CI 现在运行 `python ci/install_windows_tools.py`。脚本逐个检查 `ffmpeg -version`、`ffprobe -version` 和 Poppler 的 `pdftoppm -v`、`pdfinfo -v`、`pdfimages -v`；缺失或执行失败时按包最多尝试安装 3 次，间隔 10 秒。工具探测限时 15 秒，每次安装限时 90 秒，整个 CI 步骤限时 10 分钟。安装命令返回 0 不能替代实际工具检查，尝试耗尽仍不可用时明确失败。已有可用工具直接复用。

新增 6 项回归覆盖零退出码但工具缺失、临时故障恢复、安装超时和每个工具的执行失败。Linux 本地测试、Ruff、compileall、引用同步及两轴只读复核通过。真实视频、音乐完整性与逐页看图仍由用户验收；依赖安装检查不替代实际合成解码和 PDF 重放。

本机 Windows Python 3.12.1 独立虚拟环境安装固定依赖后，`pip check` 无冲突，CI 同组 69 项测试全部通过，无跳过。Windows 实际合成视频解码和矢量 PDF 独立双跑通过，4 类拒绝检查通过；Linux 合成重放同样通过。Windows 重放还复现了 `pdfinfo` 本地代码页日期输出与 Python UTF-8 文本解码不兼容的问题。CI 重放现保留工具输出字节，仅对 ASCII 页数、A4 尺寸和图像列表执行原有断言。没有修改宿主代码页、全局依赖或配置。证据保存在工作区 `work/agent-first-cross-host/windows-repair/windows-core-*.log`、`windows-replay-final.log` 和 `linux-replay-bootstrap.log`。
