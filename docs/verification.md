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
