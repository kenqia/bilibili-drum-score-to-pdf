# 验证与交付记录

2026-10-06。实现候选已覆盖本地转换、匿名链接兜底、纵向排序、真实清晰帧选择和明确回答后的重放。最终审查修复后，统一 CLI 的 35 项测试全部通过，实测 522.942 秒，包含五项新增内容区别、模糊恢复与保守等待验收。测试只检查用户可观察的结果，不直接测试私有算法。

此前合并 #2–#6 的 30 项回归曾通过，365.974 秒；光标接受缺失与补图恢复两项专项曾通过，48.956 秒。这些是历史切片结果。最终审查专项另通过五项，144.509 秒；一次在强模糊反例出现后主动中断的完整诊断不计为通过。

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

最终审查另复现两项问题：新增小点、细符杆或蓝点会被整行 8% 差异预算吞掉；暂时模糊会在查找后续清晰帧前停止。修复后，内容匹配只容许已有墨迹边缘一像素变化，五线附近的记号也参与检查。黑点、细符杆、蓝点及五线上的小点均返回等待，不生成声称完整的 PDF。

模糊恢复限定为清晰端点相隔不超过 3 秒、相同位置且同内容。对每个中间采样原图，只在分析中尝试半径 1 至 3 像素的轻度模糊，两端拟合的 RGB 通道最大绝对残差经 3×3 局部平均后必须处处不超过 8 级。强模糊可能把 3 像素的小点压到残差门槛以下，因此不拟合更大半径，即使两端相同也保持等待。打印图仍取真实清晰帧，不取拟合图。清晰→轻度模糊→同窗清晰可恢复；不同后窗、模糊期间新增小点及不清晰首尾都保持等待。`recoveries`、`unreadable_observations` 和等待时的 `readable_followup` 保存实际原图与源时间。该门槛无法证明采样间变化或低于残差门槛的变化，其他模糊形态或移动窗口可能仍需用户帮助。明确接受模糊缺口后仍重放到下一处接续疑点，最终 PDF 保留对应缺失位置与 complete=false。

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

下一次验收需要取得清晰的《七里香》完整视频。链接匿名获取可用且画质合格时直接使用；否则使用已说明来源的高清本地视频。通过统一入口后逐一对照全部接续、开头、结尾、重复段落和反复记号，再渲染每页检查五线、符头、符杆、连梁及分页；确有缺失时由用户明确选择。最后记录该真实输入的宽高、耗时、确认次数、页数和重复处理一致性。完成前不关闭 #7 或父规格，不把带缺口的结果写为整曲还原通过。

## 最终文件包与链接复试

审查修复后的技能 ZIP 已解压到独立位置，通过实际 `uv run` 入口再次处理 studio-exercise.mp4。退出码 0，success、complete=true，5 行、1 页 A4 纵向，7.984 秒，确认数 0。独立代理未读取仓库测试或预期文件，查看了 150 DPI 渲染的全部谱行、两处接续、原蓝色横线与数字 3，以及实际末帧 5.875 秒。没有发现错序或裁断；实物打印仍未验证。本次对应修复后的文件包，与上文 6.522 秒的审查前实验分别记录。

用户再次提供 BV1b5411x7Ku 后，最终入口又进行一次匿名链接尝试，使用 `timeout 120s uv run ...`。退出码 124，未收到 CLI JSON，结果目录没有下载视频或 PDF。本次没有实际宽高，不能记为画质不足或下载成功。上文 640×360 来自早先另一轮下载，不代表这次结果。没有登录、读取 Cookie 或认证，也未修改配置。


## #10 无谱面边缘回归

2026-10-06，使用独立 Python 3.14 环境及固定 requirements 运行统一 CLI 测试。标题卡、完整谱面、结束卡序列修复前返回 unreadable_window；修复后输出 3 行完整 PDF，并保存 0 秒开始的片头及实际 5.75 秒末帧结束的片尾证据。

新增 3 个测试覆盖 9 类输入，包括中段文字卡、局部五线、末尾残行接结束卡、模糊文字卡、模糊谱面、不可分类空白及全片只有文字卡。无依据的边缘保持等待，全片无谱面不生成 PDF。此轮没有取得真实频道视频，文字卡规则的真实样本验收仍由整体验收任务完成。

验证命令 `python -m unittest discover -s tests -p test_edge_cards.py -v`，3 项通过。既有 `test_review_regressions.py` 的 5 项回归也通过。

## Issue 15 恢复完整性

2026-10-06，在独立 worktree 通过统一 CLI 做 TDD。PDF 改写及丢失最初仍返回 success；只添加 PDF hash 后，删除 artifact 清单项仍可跳过校验。补齐清单一致性校验后均返回 failed / invalid_progress。文件系统替换边界的故障注入还复现了 PDF 已替换、旧 waiting 状态仍可被认可的问题，现已拒绝该混代结果。manifest 已提交而 state 未提交的中断也拒绝恢复。

运行 uv run --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt python -m unittest discover -s tests -p test_resume_conversion.py -v，13 项通过。覆盖 PDF 篡改与丢失、缺少 PDF/证据 hash、旧 schema、绝对与越界引用、提交中断、正常 waiting、重放、补图和回答幂等。此验证没有模拟断电或文件系统持久化顺序，不能据此声称整个目录具备断电原子事务。
