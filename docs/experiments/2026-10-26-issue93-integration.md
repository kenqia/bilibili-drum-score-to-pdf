# Issue #88 最终集成验收

本轮实施 #93，基于 `2056d6740e17580a6a0c843dd073fd01b35bc399`，独立工作区 `/home/kenqia/my_folder/bilibili-drum-issue-93`，分支 `codex/issue-93-implementation`。生产对照基线为 `28e8136a81d627a88b32bc9870bb62fb1ae28fb3`。保留原仓库修改及全部历史来源、失败和作废产物。不修改独立 Skill、认证或生产，不执行远端写入。

## 最终结果与限制

最终应用候选为 `dcc742eff50b6c986e91817c8a4124ddd7ee3aa7`，程序源码SHA-256为 `798d6a15c10aa5cf3752fc30c23e693060eb953c8bd06ebc89880b98b5551252`。程序完整回归299项、772.987秒全部通过，无跳过；同版离线重放通过。日志为 `full-regression-final-v5.log` 与 `offline-final-v2/summary.json`。两轴delta-v5复核无新增发现，原测试异常清理P2已复核关闭。

**默认九个真实来源全部受控失败，未产生默认整曲PDF。** 明确选段hgn的3至218.5000625秒成功，不能将选段结果算作默认整曲恢复。Ftn的黑底结束卡分类错误已修复，但默认转换仍在32.000至32.100秒因配准连续性证据不足拒绝。没有放宽灰色独有记号保护、RGB容差、未知区或IoU来换取成功。

PDF和谱面预览不添加程序说明文字，原谱文字保留；范围、连续性、恢复局限和未经音乐校对提示只在网站、manifest与整理记录中显示。成功状态保持 `reliable=false`。本轮未执行Skill回归、生产部署、远端推送或关闭工单。

### 准确构建、安装与浏览器

`install-final-v4/summary.json` 对准确应用提交构建源码归档、wheel和sdist。45个包文件在源码、wheel、sdist和基础/web两份独立安装间逐字节一致，两环境 `pip check` 通过，基础环境没有FastAPI/Uvicorn。wheel SHA-256为 `762816732539e2f5db03eaf3d49acbb21d7d84aebda6be8e8f794d511c9e5fba`，sdist为 `877d800bb78c6ea604d3a8b970996d107f1f59972a94fa8fec4c77eed9726061`。

基础与web安装各从仓库外运行公开Python和CLI合成转换，两份报告为 `base-contracts-final-v4/` 与 `web-contracts-final-v4/`。实际HTTP服务、独立worker与Chromium结果为 `installed-web-final-v6/summary.json` 和 `browser-summary.json`：默认与选段两个case各生成默认一页、临时A5四页，全部预览解码、下载hash、刷新恢复、默认hash/期限不变、整理记录语义及390px手机宽度无横向溢出通过。六份默认/临时/下载PDF文字层为空。浏览器未另测缓存命中或取消重试，这些属于完整回归证据。

父任务实际查看全部十张预览和对应十张PDF光栅页的contact sheet，原题名、四行音符/符干及行序保留，临时每行整页，没有程序说明文字或页脚。六张UI截图只查看顶部裁剪，不能据此声明整张网页逐像素检查。报告为 `installed-web-final-v6/root-visual-review.json`。首次v4因夹具 `fetch(blob)` 被CSP拒绝、v5因夹具 `addStyleTag` 被CSP拒绝；两次失败原样保留，v6只修测试夹具，未改产品。

### 同版真实来源

默认九源在干净的准确应用候选下串行执行，结果为 `real-final-v2/summary.json` 及各来源 `execution.json`。全部来源前后hash不变，均未发布result。失败转换未公开采样或资源摘要，相关成本为 `null`，下表秒数仅为本次公开调用总耗时。

| 来源 | 失败与位置 | 调用秒数 |
| --- | --- | ---: |
| BV1hgnb6DELn | ambiguous_scope，0.000秒存在未确认被主曲覆盖的独有谱面 | 32.694 |
| BV1FtnP6AEfA | discontinuity，32.000至32.100秒 | 47.390 |
| BV1M216BVEE1 | discontinuity，108.960至109.080秒 | 52.263 |
| BV1Xp4y157oo | discontinuity，48.236至48.427秒 | 29.617 |
| BV1JU4y1y7Zy | unsupported_layout，自动谱区边界有未能区分的墨迹 | 12.320 |
| BV1r9MyzYETL | discontinuity，17.867至17.967秒 | 43.995 |
| BV1g6XrYGEy1 | discontinuity，14.000至14.100秒 | 41.920 |
| BV1zV411W7Hj | ambiguous_scope，103.480秒主曲边界 | 27.433 |
| BV15R4y1n7Ch | ambiguous_scope，6.240秒主曲边界 | 26.689 |

同版hgn显式选段结果在 `excerpts-final-v2/hgn-3-2185000625/`，107.949秒生成19行、两页，439个artifact hash及实际PTS/time_base核验通过，无恢复块，PDF文字层为空，来源hash不变。采样进程树峰值RSS为152076288字节，观察到的临时目录峰值为117045319字节；这些是本次采样值，不是硬资源限额。父任务逐张实际查看两份预览和两份PDF光栅，首行1及末行69双终止线、原标题/作者/QR/制谱/速度、蓝光标、淡水印与原大行距保留，无工具栏、程序说明或页脚。报告为该目录的 `root-visual-review.json`，属于选段工程看图，不是音乐校对。

Ftn31至33秒的局部失败保留在此前 `excerpts-final/Ftn-31-33/`，配准代码之后未改，不将其改记为新的同版运行。最终默认Ftn已重新实际执行。以下保留各旧候选的失败与修复过程，不跨版本沿用通过结论。

## 首轮回归与修复

Python 3.12.12 下首轮完整程序回归实际运行290项，714.048秒，3项失败、1项错误。日志为 `work/engineering/2026-10-26-issue93/full-regression.log`，不能计为通过。

三项维护/缓存失败来自维护工具未将新增可选 `restoration` 纳入 manifest 与队列 summary 的严格比对。现已补齐这个可选字段，仍要求值完全相等，不接受任意额外字段。预检测试错误来自夹具自身最后位移截到下一谱行符干，现改为完整末行夹具，保留所有原预检断言，迁移记录见 `docs/test-migration.md`。上述四项针对测试32.012秒全部通过。

公开 `convert` 浅灰触边反例在1.872秒复现错误 complete：195灰度的下一行符干被只看深色的边缘检查漏掉。修复将RGB最暗分量小于245的可见记号纳入检查，与既有交付记号范围一致。边界连通块高度、面积、满宽视频边框及左右装饰的例外保持。浅灰/黑色残片拒绝、后续完整替换、灰底附属记号和细黑边保护五项针对测试15.524秒全部通过。红绿日志分别为 `pale-edge-red.log` 与 `pale-edge-green.log`。

## 验收边界

各冻结候选的实际结果分别记录在下文，不能跨版本沿用通过结论。实际页面审查由父任务单独记录，不能把生成预览、hash核验或脚本截图等同于已看图。全部成功状态仍为 `reliable=false`，不声称音乐校对。PDF 与谱面预览不添加程序说明文字；范围、连续性与恢复局限在网站、manifest和整理记录中保留。

## 两轴预审后的集中修复

候选 `872cf84f6c41c3a512e673d5cf004a9c82deecf7` 的第二轮完整程序回归291项631.505秒全部通过。独立 Standards 预审零项，Spec 预审两项P1；原报告保留在 `work/engineering/2026-10-26-issue88/review-spec-pre.md` 与 `review-standards-pre.md`。审查未将计划中的真实验收误记为完成。

父任务补充短驻留灰色小块反例。公开转换20.296秒复现错误complete，黑色原反例仍拒绝；修复稳定画面比较，拒绝匹配未知区以外可见前景到纸白的独有内容消失。灰/黑短页、回跳、动画、触边及干净翻页两项23.393秒通过。

Spec 预审的封面问题通过公开转换复现：封面外独有黑色、195灰、红色文字都会被全图IoU平均掉，三色反例4.329秒均错误complete。替代封面时现在额外逐像素核对框外原可见记号，RGB通道差超过既有8级容差即拒绝，不再额外忽略封面框外8像素带。封面反例和主曲/选段两项7.639秒通过。

另一项P1是与物理边界隔有白边的残缺五线组。公开转换在4.378秒复现两、三、四条残线均错误complete。检查现在同时查边缘附近未配成完整组的平行谱线，使用已观察完整五线的间距；不只检查首末像素。上下边缘均覆盖两、三、四条残线。宽灰水印可能将完整组的若干线并成厚块，补以水印外真实深色谱线残留证明完整五线，不能把遮挡当裁切。该联合问题先在恢复测试中失败，证据保留。

固定水印测试旧末尾本身截断的夹具按迁移记录修正，原有恢复和来源像素断言保留。修复后水印/光标恢复及上下白边残组三项11.470秒通过。该阶段尚未运行最终矩阵；后续结果见文首，不将这里的针对测试当作真实九源或安装验收。

集中修复后的七项针对矩阵42.873秒全部通过，包含灰/黑短驻留与回跳保护、黑/灰/红封面外独有记号、上下白边残组、灰底附属记号、细黑视频边框、固定水印及同色光标恢复。日志为 `work/engineering/2026-10-26-issue93/review-fixes-targeted-v2.log`。compileall 与 diff检查通过。该阶段的两轴复核及后续冻结结果见文首。

## 封面包围框复核

Spec delta复核进一步发现：蓝色空心框的整个包围框仍被当作遮挡，框内实际可见白底黑字会被丢弃。已中断 `bf8fb8e` 的最终完整回归并保留 `full-regression-final.log`，退出130，不计通过。公开转换三色框内文字反例3.947秒均复现错误complete。

封面未知区现仅包含对应候选的实际彩色连通组件像素，不再使用整块包围框。框内白底、黑灰文字及独立彩色文字继续按真实RGB核验，也不会豁免框外彩色记号。无法从实际组件证明的照片范围保守返回 `ambiguous_scope`。框内三色、框外三色与默认主曲/选段三项10.504秒通过，保留红绿日志 `hollow-cover-red.log` 与 `hollow-cover-green.log`。

## 冻结候选 7dd9f8c 的实际验收

候选 `7dd9f8c7ea5ecf53c592b696bf1aba6a90758e83` 的程序完整回归294项、698.004秒全部通过，无跳过。日志为 `full-regression-final-v2.log`。离线重放 `offline-final/summary.json` 通过，三行一页、重复转换PDF一致，输出不覆盖与输入额度拒绝通过。语法编译与diff检查通过。两轴delta复核无新增发现。

`install-final/summary.json` 记录准确提交的源码归档、wheel与sdist。45个包文件在源码、wheel、sdist及基础/web两份独立安装间逐字节一致，两环境依赖检查通过，基础环境没有FastAPI/Uvicorn。程序源码SHA-256为 `e6ef6c6c061addfe8575de9ad7b8dd9fefcbadb3869129636a384752334d3505`；wheel为 `1c030dbe8bc22fb88dbe635b4a1627cadcc6878c4be2a7e582b9dbbdf4ba04c1`，sdist为 `fbcd6dcf6c84f4c2b536e1f75da87179d862a8a91f157b87e82d79aa726594a6`。这些只证明该候选构建安装与身份，不代表安装版转换或浏览器已验收。

默认九源全部实际运行，均受控失败、没有发布result，原视频前后hash均不变。失败转换不公开采样与资源摘要，相关成本为 `null`。结果见 `real-final/summary.json` 及各来源 `execution.json`。

| 来源 | 结果与位置 | 处理秒数 |
| --- | --- | ---: |
| BV1hgnb6DELn | ambiguous_scope，开头0秒 | 31.215 |
| BV1FtnP6AEfA | ambiguous_scope，尾部226.500秒 | 28.305 |
| BV1M216BVEE1 | discontinuity，108.960至109.080秒 | 54.796 |
| BV1Xp4y157oo | discontinuity，48.236至48.427秒 | 30.277 |
| BV1JU4y1y7Zy | unsupported_layout，自动谱区边界有未能区分的墨迹 | 11.211 |
| BV1r9MyzYETL | discontinuity，17.867至17.967秒 | 38.892 |
| BV1g6XrYGEy1 | discontinuity，14.000至14.100秒 | 40.844 |
| BV1zV411W7Hj | ambiguous_scope，103.480秒主曲边界 | 23.657 |
| BV15R4y1n7Ch | ambiguous_scope，详来源诊断 | 22.612 |

同版另按既有边界运行两个显式选段。hgn的3至218.5000625秒在79.546秒生成19行、两页；439个产物hash、实际PTS与空PDF文字层检查通过，没有恢复块。父任务实际查看两份PDF渲染及两份预览，确认首尾、末69行双线与无程序说明，记录为 `excerpts-final/hgn-3-2185000625/root-visual-review.json`。这是选段正例，不是默认整曲成功。

Ftn的31至33秒在4.193秒返回discontinuity，位置32.000至32.100秒，没有发布result，来源未变。#91旧候选同选段曾成功，当前候选增加灰色独有记号保护后已失效。对旧留存15个同次原生窗口与两份页面参考逐像素比较，14个原可判同页的画面被当前检查拒绝。差异包括低饱和蓝色光标与H264谱符附近灰色振铃，RGB差不止8级，不能只加8级容差修复。诊断为 `Ftn-native-same-diagnosis.json`。未膨胀未知区、放宽IoU或删除灰色短驻留反例，暂保留这一保守失败。

## 黑底结束卡误判修复

Ftn尾部另有独立分类错误。225.9至227.8秒57个实际原生帧保留在 `Ftn-tail-native-final/`，记录源hash、实际PTS/time_base及每帧hash。子代理与父任务实际查看选定帧，225.9与226.233秒是完整第5页，226.5秒起是没有谱面的黑底熊头像结束卡。原分类把黑背景本身当作长横线，又把彩色头像当cover，错误认成遮挡谱面。这不属于末页替代见证缺失。

公开 `convert` 的黑底头像和文字结束卡合成反例1.157秒复现ambiguous_scope。无完整五线时，片段证据现在同时要求可能覆盖框外存在多数中性浅色纸白，符合固定白底谱区边界。该条件只参与分类，不扩大实际未知像素，也不放宽RGB保留。黑底片尾卡、实心封面正例及框内外黑/灰/红独有文字三项9.658秒通过。红绿证据为 `outro-card-red.log` 与 `outro-card-green.log`。真实选定帧分类检查确认完整末页保持score，原误判结束卡变为black，见 `outro-classification-fix.json`。

本修复之后已继续实际执行完整回归、同版真实来源与选段、准确构建安装、实际HTTP/worker及Chromium，最终结果见文首。上文保留7dd9f8c的失败与成功，不将它们改记为后续候选结果。

## 最终回归发现的父亡清理竞态

结束卡修复候选 `cee19a8523d6aa078d9d92f1689c12ef13a91616` 实际完整运行295项、753.457秒，一项失败，其余294项通过。`test_killed_caller_leaves_no_active_decoder_or_task_temporary_root` 在调用方被强杀、临时根已消失之后，仍观察到活动解码进程。原日志 `full-regression-final-v3.log` 保留，不计全套通过。独立复跑0.286秒通过，100次合成CLI重演也未再次复现，记录为 `killed-caller-reproduction.log` 与 `killed-caller-race-diagnosis/summary.json`，不能以重跑掩盖首次失败。

根因是父亡SIGKILL让转换进程先消失，guardian的严格root身份检查会返回空树；尚未采到、且已经没有存活受管父进程的同会话后代也可能漏掉。没有通过扫描未知会话或推断复用后的PGID解决这个问题。

确定性公开CLI反例只使用合成进程。ffprobe夹具在已知调用方子树中通过PID/PPID/SID/start-time找到guardian，暂停并确认T态后创建同会话子进程，保留管道，再让原ffprobe退出。强杀调用方，确认旧转换进程身份消失后恢复guardian。旧版在删除临时根后仍留下S态子进程，0.245秒复现最终清理断言失败，见 `guardian-anchor-red-v5.log`。早期夹具的缺失import错误和未充分扩大竞态的通过日志也保留，不把它们当作产品红例。

最小修复在guardian握手后的ready返回处将父亡信号改为SIGSTOP，并再次核对父PID，父亡时保留原转换进程身份和会话锚点。握手前仍是SIGKILL，尚不启动解码。现有guardian继续按原PID/start-time发现、冻结、终止后代，确认写入树停止后才清理，未扩大未知进程扫描或放宽PID复用保护。

权威依据为本机Linux手册 `/usr/share/man/man2/prctl.2.gz` 的 `PR_SET_PDEATHSIG` 与 `/usr/share/man/man7/signal.7.gz`。前者说明可设置任意合法父亡信号，后者说明SIGSTOP不能被捕获、屏蔽或忽略。该设置在fork子进程中清除，因此修复保留的是转换根身份，不假定解码器继承父亡信号。

确定性清理、原调用方强杀、异常转换进程/独立会话、PID复用、服务守护租约和并行SIGTERM六项3.561秒全部通过，日志 `guardian-anchor-green.log`。另通过公开CLI模拟guardian在R握手前退出，确认从未启动解码器、没有发布、来源未变与临时根清理；与确定性清理两项0.483秒通过，日志 `guardian-startup-and-anchor-green.log`。握手前后切换与守护不可用边界未改为无条件后台运行。新候选完整回归、构建安装、HTTP/Chromium和真实来源验收见文首。

后代PID复用、总期限和取消清理三项2.080秒通过，日志 `guardian-identity-budget-green.log`；语法编译与diff检查通过。

## 外部写事务与进度更新竞态

父亡清理候选 `41f01b035923e7feada6f08f3eb7d48d1680116f` 的完整回归实际运行297项、776.746秒，一项失败。外部写事务释放之后，两任务未在40秒内全部完成；原日志为 `full-regression-final-v4.log`。带任务终态、整理记录和worker输出的独立重演6.479秒通过，保存在 `sqlite-busy-diagnosis/`，不能据此抹去全套失败。

原测试在下载标记出现后申请写锁，下载进程发送的进度可能尚未由监督线程写入SQLite。仅调度器轮询处理了service_busy，任务自己的进度写入超时会中断转换。新公开HTTP/worker反例先等两任务抵达downloading写入边界，再持有真实 `BEGIN IMMEDIATE` 写事务直到至少一次阶段调用返回，触发SQLite自身的一秒busy超时。`sqlite-stage-red-v3.log` 在2.171秒复现一任务failed/conversion_failed、另一任务仍running/downloading。初版夹具缺少import导致超时、第二版固定等待1.3秒未触发任务写超时，两份原日志保留，不计有效红例。

修复只在 `Jobs.stage` 跳过真实SQLite BUSY/LOCKED映射的service_busy。页面与整理记录可能暂时显示上一阶段，下一阶段继续更新；完成决定、产物发布、终态事务和未知提交确认错误不跳过。没有重试转换、扩大SQL等待期限或放宽完成断言。确定性反例与原外部writer测试两项13.291秒通过，见 `sqlite-stage-green.log`。未知阶段commit确认、未知完成commit确认、未知领取commit确认，以及guardian握手失败和确定性父亡清理共五项6.276秒通过，见 `sqlite-ack-and-fixture-green.log`。

Standards发现的测试异常收尾也已修复：夹具先原子登记guardian/worker/probe身份，外层收到后再允许暂停guardian；即使fork之后最终decoder marker写入失败，finally仍恢复guardian并按原身份清理。最终marker正常路径已通过上述五项验证。故障注入验证见下一段；同版完整回归、离线重放与最终安装/真实来源结果见文首。

夹具故障注入已实际执行：在guardian暂停并fork之后、最终decoder marker之前强制异常，测试按预期因缺marker失败；finally中的进程和临时根清理断言通过，额外追踪的未登记合成child已消失。`guardian-marker-failure-verification/summary.json` 明确标记 `fixture_failure_teardown_only`，不能算作产品回归通过。
