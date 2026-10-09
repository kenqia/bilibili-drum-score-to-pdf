# 验证记录

2026-10-08，重构分支 `rewrite/minimal-moving-viewport` 从 GitHub 最新 main `0b4da0639c51bf121bfa0574e456409b643936af` 建立。正式产品只保留一个空间跟踪核心，旧恢复模块和旧像素例外测试已删除。

## 新鲜验证

```sh
uv run --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt python -m unittest discover -s tests -v
```

54 项测试通过。覆盖固定窗口、共同位移、连续滚动、重复内容保留、partial 转 complete、永远 partial、位移歧义、比例变化、clean/cursor 的先后观察、固定遮挡否决、独立标题、A4 整行分页、实际 PTS、原裁剪来源、跨目录 PDF 确定性以及匿名获取和中断生命周期。

新增回归测试检查底边只露下一行符杆、还未露五线的情况。完整谱行裁剪不包含下一行碎片，结尾仍有这类碎片则等待。

三个移动窗口模块共 270 行，500 行门禁和 AST 依赖防火墙通过。生产路径 grep 未发现被删除的恢复抽象。三个匿名获取模块和 requirements.txt 与 main 完全一致，无新增依赖。

## 真实 URL 双跑

```sh
uv run skills/bilibili-drum-score-to-pdf/scripts/convert.py 'https://www.bilibili.com/video/BV1rH4y1R7Rk' --output work/verified-url-1
uv run skills/bilibili-drum-score-to-pdf/scripts/convert.py 'https://www.bilibili.com/video/BV1rH4y1R7Rk' --output work/verified-url-2
uv run --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt python tests/verify_real_acceptance.py --first work/verified-url-1 --second work/verified-url-2 --report work/verified-acceptance.json
```

两次均匿名取得 video-only H.264 格式 30080，实际 1920×1080、298.6 秒，返回 success、complete=true、12 行和 2 页 A4。每行 effective DPI 为 264.182。逐页检查标题、tempo 80、拍号、首尾、符杆和上下边缘，未见光标覆盖或 partial row 混入。原蓝色水平休止记号保留为灰度。

| 指标 | 第一次 | 第二次 |
|---|---:|---:|
| seek_count | 57 | 57 |
| 完整画面分析 | 57 | 57 |
| selected_keyframes | 15 | 15 |
| 候选观察 | 242 | 242 |
| 解码秒数 | 18.235 | 15.005 |
| 匿名获取秒数 | 7.694 | 6.181 |
| 转换秒数 | 52.649 | 42.348 |
| URL 到 PDF 总秒数 | 60.343 | 48.529 |
| 解码临时盘峰值 bytes | 520564 | 520564 |

57 次完整画面分析相对旧约 599 次下降约 10.5 倍。candidate_observations 是谱行可用性评估数量，没有计为完整画面分析，也没有谱行像素身份比较。稳定性复核和局部采样包含在 57 次中。

peak_temp_disk 是单 PNG 解码临时目录的实测峰值，不包含匿名下载 staging 和保留的交付证据。decoded_reported_frames=142 是 showinfo 报告的解码画面，含末尾流式核查；seek 前由解码器丢弃的帧未测量。total_elapsed 包含匿名获取和转换，不包含下面的独立验收过程。

## 来源与一致性

验证脚本独立重解码标题及 12 条所选谱行，逐像素核对 source_frame/bbox、original_image、selected_candidate 与灰度打印图，并重新检查完整谱行边界。每轮额外 13 次来源解码和 12 次几何复核仅用于验收，不属于转换的性能指标。

两次 row count、index、global_y、selected timestamp、source bbox、原裁剪 hash、PDF page/bbox、标题图和 150 DPI 渲染页面完全一致。PDF 字节也一致。

PDF SHA-256：`58f0707765576976aa7f1887633b8acc98ef874f65d8c0826678065d1844b0ab`。

| row | global_y | actual PTS 秒 | source bbox | PDF 页 |
|---|---:|---:|---|---:|
| 0 | 485.0 | 0.0 | [0, 417, 1920, 582] | 1 |
| 1 | 676.0 | 2.0 | [0, 589, 1920, 779] | 1 |
| 2 | 867.0 | 148.0 | [0, 391, 1920, 592] | 1 |
| 3 | 1058.0 | 168.0 | [0, 204, 1920, 395] | 1 |
| 4 | 1249.5 | 152.0 | [0, 655, 1920, 845] | 1 |
| 5 | 1440.75 | 158.0 | [0, 847, 1920, 1026] | 1 |
| 6 | 1632.0 | 176.0 | [0, 650, 1920, 837] | 1 |
| 7 | 1823.5 | 174.0 | [0, 838, 1920, 1022] | 1 |
| 8 | 2014.25 | 194.0 | [0, 634, 1920, 836] | 1 |
| 9 | 2205.25 | 192.0 | [0, 836, 1920, 1014] | 1 |
| 10 | 2396.5 | 222.0 | [0, 509, 1920, 697] | 1 |
| 11 | 2587.25 | 246.0 | [0, 699, 1920, 877] | 2 |

## 环境与限制

实测环境为 Python 3.14、uv 0.9.11、ffmpeg 4.4.2、Poppler 22.02.0。依赖沿用 main 的 Pillow 12.3.0、NumPy 2.5.3、OpenCV 5.0.0、ReportLab 5.0.1、yt-dlp 2026.08.19。

结论只覆盖此真实样本与合成布局。完全周期几何、采样之间换谱、快速整行跳跃、任意未知遮挡以及其他真实视频仍有边界，见 architecture.md。原图选择不等于能自动发现所有遮挡，打印前仍应逐页复核。

以上记录是 `0b17857` 集成前的验证。当时提交只在本地重构分支，main 和 GitHub Issues 尚未修改。


## 2026-10-08 单分支集成复核

用户选择 `rewrite/minimal-moving-viewport` 的 `0b17857` 作为 main 的产品基准。采用快进保留原有提交，追加本节记录，不合入其他实验分支或工作区中的未提交行为修改。

在独立、干净的 `0b17857` 工作目录重新执行上面的 unittest 命令，54 项全部通过。随后使用同一 URL 入口运行两次，再执行 `tests/verify_real_acceptance.py`，独立重解码原帧并核对逐行来源、灰度打印图、几何、光标检测、页面渲染和 PDF 字节一致性。

两次均匿名获取 1920×1080 输入，返回 success、complete=true、12 行和 2 页 A4。每次分析 57 帧，URL 到 PDF 总耗时分别为 55.458 秒和 46.768 秒。本次没有重跑旧模型耗时基准，也没有实物打印。

本地复核文件位于 `work/integration-20261008/`，包含 tests.log、url-1、url-2 和 acceptance.json。该目录还保存两个关联仓库的清理前 Git bundle、分支与 worktree 清单及未提交补丁。历史工作目录保留文件，实验分支引用删除前先解除 worktree 的分支占用。

Issue #24–#31 按当前简化方案取代收尾，不能把原规格中的 fallback、聊天恢复或跨模型恢复标为实现。#22 按已完成的耗时改善收尾。#12、#18、#20、#21 继续跟踪未完成工作。

## Agent-first 固定谱面记录，#33

统一 CLI 是已确认测试边界。2026-10-08 首次 RED 运行 Agent workflow 测试时，入口拒绝 --operation。添加最小 prepare/submit/export/replay 后，同一测试 GREEN。第二轮提交合法字段但重复 schema_version 的 JSON，原解析接受并保存，负例 RED；改为拒绝重复键后 GREEN。测试命令如下。

```sh
uv run --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt python -m unittest discover -s tests -p test_agent_workflow.py -v
uv run --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt python -m unittest discover -s tests -v
```

固定合成视频的保存决定得到 3 行、独立标题、1 页 A4；原裁剪 RGB 与源 bbox 相等，export/replay 的 PDF 字节一致。覆盖非法协议、未知引用、缺少视觉证据、漏行、未决疑点、重复键、NaN/Infinity、低清、空谱面、目录保护，以及观察包和原视频变更。新增 3 个测试，既有 54 个测试继续通过，共 57 个。

这些是保存决定的离线执行验证，未证明真实 Agent 视觉识别能力。真实 B站整曲 Agent 审阅、资源比较、CI 和默认切换由后续票验收。默认转换未改采样或身份规则，本票未重复真实 URL 双跑。

## Agent 原生细节与边界试验 #34

2026-10-08，统一 CLI prepare → submit → export → replay 的合成测试通过；完整仓库 59 项测试在 53.801 秒内通过。v1 仍可重放；v2 接受原生 ROI 和与规则建议不同的整行框。负例覆盖缩略图坐标、越界、细节覆盖不足、未确认边缘、光标与遮挡、精修超过 8 像素及未确认精修。实际短行后留白、单行无规则建议、窄光标先出现、宽遮挡后出现均通过原帧选择；全程宽遮挡返回 waiting，不保存可导出决定。

实际 Agent 观察另行执行，不能以固定 JSON 测试冒充。用仓库绘制的三行公开合成谱面制作 2 秒视频，前 1 秒蓝色矩形覆盖第一行，后 1 秒移除。首帧 0.0 s、中帧 1.0 s、末帧 1.75 s。审阅者通过 view_image 实际查看对照图、三张原帧、第一帧左上细节及中帧 6 张原生细节。看到首帧遮掉第三个音符和弧线右侧，中末帧三行分别有 4、5、6 个音符，第一行上方 `(x)` 与完整弧线、下方 `pp` 可见；稳定红色原图记号保留，不作擦除。

选择中帧三个完整整行，实际 PTS 均为 16384，time_base 为 1/16384，原裁剪宽 1120 像素。CLI 导出 1 页 A4。独立 Pillow 核对三条 RGB 原裁剪与 source_frame+bbox 逐像素一致，打印图与原裁剪 convert('L') 一致。实际查看第一条 RGB、灰度及 Poppler 渲染 PDF，`(x)`、弧线、`pp` 和原红色记号的灰度保留。保存决定重新 replay 的 PDF 字节一致。

源视频、观察包、图像呈交 ID、公开提示词和可见模型标识、决定与两个输出保存在仓库外共享实验目录 `work/agent-first/visual-34`，不提交生成媒体。精确模型版本不可见，记录 unknown。该试验只有一组合成成对图像，证明流程与一次实际观察，不证明真实整曲识别、通用锐度校准或中央遮挡恢复。默认 moving viewport 未切换，本轮不重复其 BV 性能验收。

## Agent-first BV 入口记录，#40

2026-10-08，测试边界为统一 CLI 与任务产物。第一个 tracer bullet 使用现有 yt-dlp、HTTP 和 DNS 外部边界提供合法合成视频，不替换内部工作流。RED 时 BV 链接被当成本地路径，返回 invalid_input。prepare 接入原匿名 acquire 后 GREEN；同一原视频的 BV 与本地观察包进入保存决定的 submit/export 后，三行原裁剪 hash 和 PDF 字节相同。任务目录保留获取后的原视频，来源与 SHA-256 进入观察包和最终 manifest。

第二个 tracer bullet 在匿名后端拒绝时 RED，InputError 尚未转换为结果 JSON。增加 acquisition-only 脱敏诊断并复用原重试条件后 GREEN，BV 重试和本地替代都可生成观察包，已有观察和用户文件拒绝覆盖。负例继续覆盖初始 HTTPS、分 P、媒体目标、私有 DNS、重定向、不可解码视频、大小限额、总 deadline 和 publication staging 清理。沿用原获取能力，没有修复 #20。

```sh
uv run --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt python -m unittest discover -s tests -p test_agent_link_input.py -v
uv run --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt python -m unittest discover -s tests -v
```

专用四项测试通过。完整仓库 61 项测试通过，运行耗时 52.761 秒。这里是受控获取与保存决定的执行验证，没有声称真实 URL 获取或 Agent 视觉能力通过。#41 承担真实整曲审阅和默认切换。本票未改变默认谱面采样、谱行身份或原匿名下载安全门槛。

## 保存决定离线 CI，#39

2026-10-08，统一 CI replay 命令的第一轮 RED 因脚本不存在而失败。实现后 GREEN，受控固定视频准备、提交、导出与重放得到 3 行、1 页 A4，源原裁剪像素与 PDF 字节一致，effective DPI 不低于 150。未知版本、越界坐标和损坏图像分别得到 invalid_decision、invalid_decision 和 source_mismatch。另用缺少 ffmpeg 的子进程验证失败证据只保存异常类型，不泄露路径或日志。全量 59 个 unittest 本地通过，新增 CI command 的 2 个测试再次通过。原裁剪由独立 ffmpeg 重解码核对，DPI 同时按原裁剪宽度与 PDF 放置宽度计算。

实际命令及 artifact、配置影响和回滚说明见 [离线 CI](agents/offline-ci.md)。此记录是本地验证；GitHub hosted 成功运行需发布后另行记录。本票不修改或关闭 #21，也不把固定决定重放当作 Agent 视觉能力验收。

## 连续长谱视觉对应记录，#35

统一 CLI 的第一轮 RED 因 schema_version=3 未实现而拒绝；增加空间观察、相邻对应与覆盖检查后 GREEN。下一轮等待反例虽然拒绝导出，但 issues 为空，RED；保存前后图像与时间区间后 GREEN。验证停留不重复、等间距行的明确视觉对应、同内容不同空间实例、半行等待后选完整原帧，以及共同位移矛盾、比例变化、单行重叠、缺少首尾、缺少共同身份、成环、交叠、漏行和重复实例反例。

```sh
uv run --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt python -m unittest discover -s tests -p test_agent_continuity.py -v
```

三项 CLI 测试通过，固定保存决定得到 4 条空间行，global_y 为 220、440、660、880；export/replay 的 PDF 字节相同。既有 v1/v2 来源检查继续保留。几何测试的预期位移来自手工构造的 220 像素推进，不用脚本结果反推预期。

另以 view_image 实际查看 2 秒公开合成视频的三帧对照、三张原图和 8 张原生细节。0.0 s 可见 A/B/C，1.0 s 可见 B/C/D，1.75 s 与中帧相同。B/C 的可见字母与位置支持 220 像素推进；音符形状相同，D 仍为后续空间实例。字母只是视觉测试标记，不是假冒真实曲谱识别。首帧三行及中帧 D 的五线、圆形音符、字母与两侧边界在原生细节完整可见，选择这些单帧框导出 4 行、1 页 A4。

实际审阅材料、仅实际阅读图像 ID 的决定、公开提示词及可见模型标识保存在仓库外共享 `work/agent-first/visual-35`。模型精确版本不可见，记录 unknown。独立 Pillow 核对四条 RGB 原裁剪与源 bbox 逐像素相同，灰度图与原裁剪转灰度相同，保存决定 replay 的 PDF 字节与首次导出相同。这只是短合成段的一次实际观察；三张稀疏图不能证明真实整曲覆盖，本票未重复旧默认的 BV 双跑，也未宣称未采样画面没有新内容。

#35 合入当前 integration/agent-first 后无需冲突处理。全量 68 项 unittest 于本工作树通过，耗时 74.144 秒；git diff --check 通过。无新生产依赖，无远端或配置操作。

## 有界自适应观察记录，#36

统一 CLI 第一轮 RED 因 supplement 操作不存在而失败。加入绑定版本的局部观察请求后 GREEN。负例覆盖非有限和布尔时间、越界、重复时刻、空请求、旧版本、重复 ID、八次请求后的累计耗尽；旧观察字节保持，耗尽不生成 PDF。12 秒夹具覆盖长停留、20 像素小幅推进和短暂遮挡变化，检查真实首尾及组间共同帧。补采短暂清晰行与始终遮挡两个受控保存决定分别导出及 waiting。

另一次实际看图审阅保存在仓库外 `work/agent-first/visual-36`。view_image 读四帧对照、全部四张原图及 0.25 秒的两张重叠原生细节。首、中、尾的蓝矩形遮住谱行中部；0.25 秒露出四个符头与符杆、完整五线和 ROW 1 标记。按该单帧裁剪导出一行 PDF，保存决定 replay 的 PDF 字节相同。决定只记录七个实际看过的图像 ID，模型精确版本未知。本次是合成固定一行的实际补采观察，不是整曲覆盖证明；始终遮挡由独立 CLI 保存决定反例验证。

```sh
uv run --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt python -m unittest discover -s tests -p test_agent_sampling.py -v
```

补采专题五项测试覆盖实际 PTS 空转；此前全量 71 项测试通过，耗时 102.998 秒。后续最终全量记录以集成结果为准。协议不要求固定 4/2 秒间隔，没有恢复撤回的补丁。

同一公开源视频的自适应 prepare 实测为 waiting，48 张原生图、255 张 160×90 导航图、770 张细节和 48 张拼图组成帧。生成像素合计 327,784,320；48 次 seek、124 个 decoder reported frames、原生解码 13.257 秒、缩略导航 10.227 秒、原生处理阶段 71.471 秒。该次 prepare_elapsed 不含导航，后续代码另外记录 total_elapsed 与 native_processing_elapsed。观察包 567,687 字节，后续读取已验证。还未做这批图的实际 Agent 整曲审阅，实际呈交像素和模型成本尚未测；不能拿这些候选数断言完整。公共包保存在仓库外 `work/agent-first/adaptive36-public`，#41 可基于此复查或从匿名 BV 入口重新准备。

## 有序谱面段记录，#37

统一 CLI 的 v4 两段决定首轮 RED 因版本未支持而失败。实现分段审计后 GREEN，单帧首段与两帧停留的次段得到 6 行，段内 global_y 都是 220、440、660，scroll_offset 独立从 0 开始。跨页同名实例与同节奏均保留，两个 Agent 指定原生标题进入 PDF；保存决定重放的 PDF 字节相等。第二轮 RED 暴露重复标题及缺帧检查顺序问题，第三轮 RED 暴露行外区域 placement 与原帧上下顺序矛盾，修复后两项专用 CLI 测试通过。负例覆盖跳页、回跳、相似页面仍无法确认、缺接续证据、缩放、布局突变、换页边缘残行、缺段帧、缺边界、未检查行外符号及重复区域。waiting 保留前后截图和实际时间。

```sh
uv run --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt python -m unittest discover -s tests -p test_agent_segments.py -v
uv run --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt python -m unittest discover -s tests -v
```

另以实际 view_image 查看公开 2 秒合成视频的对照图、三张原帧及两页共 12 张原生细节。可见第一段为 bar 1、2、3，第二段为 bar 4、5、6，末帧与第二段相同；两页标题、tempo 80、五线及单音符完整。音符形状相同仍保留为两个段中的六个实例。这里的小节文字是合成测试的明确接续标记，不假冒真实曲谱识别能力。实际呈交的 16 张图 ID、公开提示词、可见模型标识、决定和产物保存在仓库外共享 `work/agent-first/visual-37`。模型精确版本不可见，记录 unknown。

CLI 导出 6 行、两个独立标题、1 页 A4。独立 Pillow 核对八个 RGB 原裁剪与 source_frame+bbox 逐像素相同，灰度图与 RGB 转灰度相同；replay PDF 字节一致。实际查看 Poppler 渲染，标题、tempo 及 bar 1 到 6 顺序保留。全量 70 项测试通过，耗时 85.032 秒；最后增加 placement 检查后，两项专用测试再次通过，耗时 9.726 秒。此票没有新增依赖，没有修改默认转换。稀疏观察仍不能证明未采样时间无隐藏页，真实整曲 Agent 验收由 #41 完成，未重复旧默认 BV 双跑。


合入 #37 有序谱面段后，全量 75 项通过，111.020 秒；新增预算校验的 RED 发现被改成负数的累计 requests 曾被接受。固定脚本 LIMITS 并校验有限非负成本、整数计数后，补采专题 6 项 fresh 通过，24.626 秒。采样观察包的 limits 不能自行放宽资源上限。git diff --check 通过。实际 PTS 空转和预算记录反例各自走过 RED/GREEN。


### #38 恢复实验

统一 CLI 的 `tests/test_agent_resume.py` 覆盖两帧累计前缀接受、退出后的 resume、相同 ID 重试、冲突与显式修订、未审尾部阻止导出、最终四个空间实例无重复及独立 PDF 字节重放。固定夹具只有协议决定，没有实际视觉能力结论。失败补采实测保留预扣请求和解码预算，旧包仍可核验，旧完整结果不能直接导出。多文件发布中断夹具通过 resume 完成 hash 核对及提交；真实 SIGTERM 分别在首张 prepare 原图、补采预扣状态及首张 export 原图出现后发出，原证据保留，重试不能覆盖。未知任务版本与历史篡改拒绝。

## Agent 保存决定的独立执行核查

使用现有 Poppler 的 pdfinfo 和 pdfimages，不增加生产依赖。先将同一个已接受决定 export、replay 到两个新的结果目录，再运行：

```sh
uv run --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt python tests/verify_agent_acceptance.py --first /absolute/first --second /absolute/replay --report /absolute/report.json
```

脚本独立用 ffprobe 获取 time_base，再用 FFmpeg 按整数 PTS 重解码所选帧。它核对保存原帧、RGB 原裁剪与原帧 bbox、原始灰度像素、来源 hash、行序、A4 页数、DPI 和行间位置。pdfimages 提取 PDF 中的每个嵌入图，按页、尺寸和灰度像素核对所有谱行、标题与行外区域，包含重复出现的图块。相同页数和尺寸但嵌入像素不同的 PDF 会拒绝。

两份报告和 PDF 字节必须一致。该脚本只核对保存决定的执行，`visual_content_verified_by_this_script=false`。完整性、细小记号、遮挡、跨帧对应和分页的实际可读性仍须独立看图核查；默认流程的切换须另有真实双份 Agent 视觉验收，本轮记录见下文。

### #41 第一份真实 Agent 审阅记录

2026-10-09，第一份实际审阅使用匿名取得的 BV1rH4y1R7Rk 第一 P，原生 1920×1080、298.6 秒。导出与 replay 使用提交 `513695ccecd7cf2ad8da51985f3fe818644b4c96`。独立来源与 PDF 验证脚本来自提交 `80c706c`。原视频 SHA-256 为 `80f9a8d19515cf624d7d13c27ea758e88118fddb4341fa06deaad040272877fe`。

root 实际审阅原图、选行细节与两个渲染页面后记录完整 12 行、2 页 A4，最低 effective DPI 为 264.182。记录确认标题、tempo 80、拍号、装饰音、ghost 括号、附点、重音、渐强线与末尾双线未截断。保存决定的 export/replay 通过独立重解码 9 个实际 PTS、13 个 PDF 嵌入图块以及 RGB 原裁剪和灰度像素核对，PDF 字节一致。PDF SHA-256 为 `0aebe26fb4c3bc471f3e3342fb1011f4e40c96b602828e38f2fcc419b6c26aba`。这项执行核对不能替代第二份独立视觉审阅。

本轮外部证据保存在 `work/agent-first/real-41/root-review/decision.json`、`verification.json`、`cost-report.json` 以及 `root-output` 和 `root-replay`。这些是执行会话中的外部文件，不在仓库中。

| 已测阶段与指标 | 第一份 Agent 路径 | 旧路径同一本地输入 |
| --- | ---: | ---: |
| 原生完整帧分析 | 48 | 57 |
| 导航缩略检查 | 255 | 无此阶段 |
| 源视频解码秒数 | 16.768，prepare | 16.697 |
| prepare 总秒数 | 89.871 | 无此阶段 |
| 转换总秒数 | 未测完整 Agent 过程 | 52.152 |

第一份记录列出实际呈交的 68 个唯一图像 ID，源图像像素合计 122,079,360。canonical comparison 实际呈交时缩放为 482×2048；源图像像素不等于模型编码后的像素。重复呈交次数、模型编码像素与实际推理耗时未知，模型 token 保留 null。生成图数不能代替实际呈交图数，prepare 与旧转换的计时边界也不同，不能据此宣称提速。第二份独立审阅与默认切换记录如下。

### #41 第二份独立审阅与默认切换

第二份 export/replay 同样使用提交 513695ccecd7cf2ad8da51985f3fe818644b4c96，独立验证脚本来自 80c706c。盲审使用第一份决定产生前保留的同源观察包，独立阅读原图、细节与两个 PDF 渲染页。两份判断均确认 12 条完整空间谱行、2 页 A4、最低 264.182 effective DPI，未决列表均为空。第二份 export/replay 独立核对 10 个实际 PTS 和 13 个 PDF 嵌入图块，执行来源与 PDF 字节一致。第二份 PDF SHA-256 为 `9107f33e04f1286b74035428ba0664d272ecfc3756c5d4a595145c7006dfb1f3`。

独立决定在第 4、7 条打印行选用了不同的合法原帧和边界，对应原谱标记 47、60。root 实际比较这些裁剪，确认保留相同完整音乐内容；其余选帧框一致。两次独立判断之间不要求 PDF 字节一致，逐份保存决定的 replay 则要求一致。源视频开头静态蓝色 8/休止记号持续存在，不能断言它来自作者配色或应用选择，原样保留后仅转灰度，不声称已还原。

第二份实际呈交 94 个唯一图像 ID，源像素合计 145,382,400；模型编码像素未知。可见模型标识为 GPT-6，精确版本 unknown，token 与推理耗时 null。两份审阅使用同一 prepare 观察包，不能把它计为两次独立获取或 prepare；导出阶段仍有来源重解码。第二份外部证据为 `blind-review-current/review.md`、`verification.json`、`cost.json`、`blind-output-current` 和 `blind-replay-current`。差异记录为 `real-41/independent-review-comparison.json`。

盲审最初的裸 uv 入口返回 invalid_input，使用仓库 requirements.txt 的 --with-requirements 入口后 prepare 之外的提交、导出和重放通过，命令记录在 `blind-review-current/commands.txt`。当前使用说明统一采用该已验证环境，不新增生产依赖。

双份实际视觉审阅、逐份保存决定的来源与 PDF 重放核对通过后，#41 将默认 CLI 和 Skill 切为 prepare。无图像能力、视觉疑点、几何冲突、换页缺口、预算耗尽、损坏记录与中断恢复仍由离线负例覆盖。实际内容结论仅覆盖本真实样本，未采样区间仍不能证明没有隐藏换谱。完整产品回滚到旧稳定提交 23ec65459807bed7a51f3fa0f1e9c08b51cc63dc，使用新结果目录并保留旧任务，不自动迁移。


默认切换后的本地完整回归为 84 项，133.370 秒通过。统一入口的默认 prepare 先记录 success 与 waiting 不符的 RED，再验证 waiting/review、resume 证据不变且无 PDF 的 GREEN。旧转换测试显式传 --operation convert 保留原断言。CI 的合成固定决定重放脚本也通过，范围仍为 fixed_decision_replay_only；这些本地结果不替代最终集成提交的 hosted CI。

## 2026-10-09 最终 review 修复验证

最终实现与测试快照为 `f7e176568a6309ffed76dd58e8ca50e40cd21219`，基于 `988b098`。统一 CLI 的未知观察引用先复现 waiting，非法引用类型还会落到 invalid_input；修复后均返回 failed/invalid_decision，合法引用的身份、帧和 bbox 冲突仍 waiting/review_required。

v5 封装 v4 的同一末段续批先复现 failed/existing_decision。修复允许 frames、rows、observations、transitions 追加已接受前缀，同时保护此前各段、末段元数据、行外区域与已接受列表内容。合成用例覆盖新段翻页追加、末段继续观察、新增空间谱行、无 revision 的旧内容修改拒绝，以及显式 revision 保留三份历史。

超大整数 `10**1000` 的 spacing、staff_y、补采范围与 timestamps 先复现 stdout 空和 OverflowError。数值验证器现在将转换溢出判为非法输入，统一 CLI 返回脱敏 failed JSON 与非零退出码，没有 traceback，原观察包及帧证据不变。段预检后的重复字段、帧引用与全段顺序检查已删除，保留前置预检及错误顺序；这项无行为变化清理没有新增镜像测试。

CI 合成重放使用以下命令通过，验证时的生产代码与上述快照相同：

```sh
uv run --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt python ci/verify_agent_replay.py --output /tmp/agent-first-review-fixes-ci-replay
```

结果范围为 fixed_decision_replay_only，3 行、1 页，最小 effective DPI 156.996，原裁剪相等，跨目录 PDF 相等；未知版本、越界和损坏图像分别返回预期失败。PDF SHA-256 为 `532b7cb98af23c0cc0b9fa10c0a04e459daf3686a2f9bc96de1c54a24f4b8f10`。这些结果不代替 hosted CI 或真实视觉验收。既有双份独立真实看图记录和原决定保持不变，最终集成提交的真实保存决定重放另行记录。

完整回归在 `f7e1765` 保存全部代码与测试后重新执行，88 项测试、173.954 秒通过：

```sh
uv run --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt python -m unittest discover -s tests -v
```

此前运行中的旧测试快照因补强 CLI 退出码和 stderr 断言而中断，不计为最终通过记录。上述全套执行期间只追加此验证文档，没有修改生产代码或测试。`git diff --check` 通过，已将最新 integration/agent-first 合入修复分支，结果为 Already up to date。
