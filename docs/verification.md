# 验证与交付记录

2026-10-06。实现候选已覆盖本地转换、匿名链接兜底、纵向排序、真实清晰帧选择和明确回答后的重放。合并 #2–#6 后，统一 CLI 的 30 项测试全部通过，实测 365.974 秒；光标接受缺失与补图恢复两项专项也通过，48.956 秒。测试只检查用户可观察的结果，不直接测试私有算法。

《七里香》没有合格高清输入，整曲顺序、全部接续位置和打印可读性尚未验收。#7 与父规格 #1 保持未完成。结构校验、合成测试和独立调用成功都不能替代这项验收。

## 已核查的输出

下表为各实施切片的实际输出记录。它们是不同输入、不同切片版本的实测，不是最新版本的统一性能基准。耗时不作承诺。

| 输入与验证 | 谱行 / 页数 | 确认数 | 转换秒数 | 结果 |
| --- | --- | --- | --- | --- |
| 固定 1280×960、2 秒，标题/速度/4/4 与 15 根五线 | 3 / 1 | 0 | 3.767 | A4 渲染后可读，完整保留符头、符杆和行下标记 |
| 固定 1280×2150、2 秒，八行分页 | 8 / 2 | 0 | 3.252 | 两页逐页查看，分页在谱行之间 |
| ABC→BCD→CDA，1280×960、6 秒 | 5 / 1 | 0 | 6.436 | 输出 ABCDA，后来的 A 没被全局去重；全部两处接续与首尾已核查 |
| 移动浅蓝光标后出现清晰整行，1280×960、6 秒 | 3 / 1 | 0 | 4.998 | 选实际干净画面，符头/符杆/连梁及原蓝色休止横线/数字保留 |
| ABC→DEF→EFA，明确接受无重叠处缺失 | 7 / 2 | 1 个模拟答案 | 5.525 | C 与 D 之间标出缺失，末尾 A 与限制说明保留；complete=false |
| 独立复制包调用，studio-exercise.mp4，1280×960、6 秒 | 5 / 1 | 0 | 6.522 | complete=true，A/B/C/D/E 与两处接续正确；仅代表本合成输入 |

持续遮挡返回编号原图、时间和 `cursor_occlusion`，不自动猜补。恢复测试覆盖没有回答、未知或无效回答、完整单行补图、明确接受缺失、重复判断、原视频/状态损坏拒绝以及重复执行不插入重复谱行。有效回答后会重放到问题后面的窗口，不将保存的前缀当作整曲。

同一本地排序夹具重复处理，谱行图片内容与顺序、源时间一致；不要求 PDF 文件字节一致。清晰度与有效 DPI 是启发式指标，仍需查看渲染页。实物打印及浅灰记号的纸面对比度未验收。

## 真实样本与网络结果

[《七里香 周杰伦 动态鼓谱》](https://www.bilibili.com/video/BV1b5411x7Ku)公开元数据为 1920×1080、297 秒。早先匿名请求取得 quality=16 的完整视频，ffprobe 实测 640×360、296.363 秒。该本地文件经统一入口返回 `failed/low_resolution`，0.984 秒、确认数 0，没有生成整曲 PDF。完整低清视频只用于布局探索和低清拒绝验证。

后来直接调用新 CLI 的在线 smoke check 用 `timeout 30s` 设外部时限，退出码 124，在获取完成前停止，没有下载结果，也没有取得本轮实际宽高。这与早先匿名下载是两次不同实验，不能合并成新 CLI 在线下载成功。链接成功集成测试用替代 urllib 公开传输响应，实际下载、解码和生成夹具 PDF；它证明集成路径，不证明外部接口持续可用。

没有登录、Cookie、密钥或绕过限制的重试。媒体签名地址只在内存读取，未进入记录、日志或子进程参数。接口与停止条件见 [包内维护说明](../skills/bilibili-drum-score-to-pdf/references/anonymous-input.md)。

## 独立实际调用与文件包

独立代理只得到复制后的 skill 与一个原始合成视频，显式使用该 skill，没有读取项目测试或预期文件。实际运行路径为：

```sh
uv run /mnt/c/Users/26960/Documents/Codex/2026-10-06/https-github-com-kenqia-bilibili-drum/work/evidence/forward-skill/skills/bilibili-drum-score-to-pdf/scripts/convert.py /mnt/c/Users/26960/Documents/Codex/2026-10-06/https-github-com-kenqia-bilibili-drum/work/evidence/forward-input/studio-exercise.mp4 --output /mnt/c/Users/26960/Documents/Codex/2026-10-06/https-github-com-kenqia-bilibili-drum/work/evidence/forward-use/result
```

退出码 0，success、complete=true、无疑点或缺口。150 DPI 渲染后核查标题 Studio exercise、tempo 88、4/4、五线、符头、符杆、连梁及 A 至 E 标记；原蓝色横线与数字 3 转为浅灰后仍能辨认。两处接续分别在 1.5/2.0 秒和 3.5/4.0 秒，开头 0.0 秒，实际结尾 5.875 秒；另取源视频末帧对照一致。本次输入没有跨段再演奏的重复段，不能代替 ABCDA 夹具的重复保留验证，也未做实物打印。

skill-creator 的 `quick_validate.py` 返回 `Skill is valid!`，检查了命名、frontmatter 和占位符。CLI `--help` 可执行；实际转换另由上述独立调用验证。匿名输入与恢复细节均在包内 references 中，单独复制 skill 仍可运行绝对脚本路径。文件包没有安装到全局技能目录，未修改 Codex 认证、配置、hooks、MCP 或全局 Python。

## 工具与依赖

WSL，Python 3.14.0、uv 0.9.11、ffmpeg/ffprobe 4.4.2-0ubuntu0.22.04.1、Poppler 22.02.0。脚本支持 Python 3.12 或更高版本。顶层 Python 依赖同时在 PEP 723 和 requirements.txt 固定版本，只在独立环境安装。

| 依赖 | 实测固定版本 | 用途 | 安装元数据许可证字段 |
| --- | --- | --- | --- |
| Pillow | 12.3.0 | 裁剪、原图与灰度打印图 | MIT-CMU |
| NumPy | 2.5.3 | 像素与谱行分析 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 |
| opencv-python-headless | 5.0.0.93 | 五线定位、相邻行比较、真实候选质量 | Apache 2.0 |
| ReportLab | 5.0.1 | A4 排版，整行分页与缺失标记 | BSD |

许可证字段来自本次已安装 distribution metadata。交付包不包含这些依赖的二进制文件；uv 根据声明安装运行依赖。没有额外识别 API 或付费服务。

## 复核命令与剩余验收

在完整仓库根目录运行已有验收测试。需要 ffmpeg、ffprobe、uv、pdfinfo、pdftoppm 和 pdftotext；测试中的字体使用 WSL 已有 DejaVu Sans。

```sh
uv run --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt python -m unittest discover -s tests -v
uv run skills/bilibili-drum-score-to-pdf/scripts/convert.py /absolute/path/to/video.mp4 --output /absolute/path/to/new-result
uv run skills/bilibili-drum-score-to-pdf/scripts/convert.py --resume /absolute/path/to/result --answers /absolute/path/to/answers.json
pdfinfo /absolute/path/to/result/score.pdf
pdftoppm -png -r 150 /absolute/path/to/result/score.pdf /absolute/path/to/review/page
```

恢复答案由 Codex 根据聊天中的明确选择写入，不要求用户写 JSON。协议见 [包内恢复说明](../skills/bilibili-drum-score-to-pdf/references/resume.md)。无回答不默许确认；已有结果目录不能作为新转换目标。状态 JSON 原子替换，但不是跨整个目录的数据库事务；异常中断导致不一致时报告未能恢复并保留文件。

实施期间一次小型 Python 文档编辑脚本在 import pathlib 阶段遇到 ENOMEM，尚未执行修改。约 995 MiB 可用内存、1908/2048 MiB swap 已用。未终止用户后台进程或修改全局设置，最终完整转换回归通过。该环境事件不计为转换测试失败。

下一次验收需要清晰的《七里香》完整本地视频，并说明来源。通过统一入口后逐一对照全部接续、开头、结尾、重复段落和反复记号，再渲染每页检查五线、符头、符杆、连梁及分页；确有缺失时由用户明确选择。最后记录该真实输入的宽高、耗时、确认次数、页数和重复处理一致性。完成前不关闭 #7 或父规格，不把带缺口的结果写为整曲还原通过。
