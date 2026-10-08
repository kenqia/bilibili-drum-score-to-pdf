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

全部提交留在本地重构分支，main 未修改。未推送、发布、修改或关闭 GitHub Issues；未改动认证、Cookie、Codex 全局配置或已安装 skill。
