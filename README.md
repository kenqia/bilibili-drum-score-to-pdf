# B站动态鼓谱转 PDF

输入 B站 BV 链接或本地视频，将视频中已有的白底多行鼓谱整理成 A4 纵向 PDF。程序把视频当作一张长谱的移动窗口，用五线几何跟踪谱行，再从多个时刻选择完整、无遮挡的真实原图。

## 运行

需要 Python 3.12+、uv、ffmpeg 和 ffprobe。uv 使用独立环境运行仓库已声明的依赖，无需登录 B站或配置 Cookie。

```sh
uv run skills/bilibili-drum-score-to-pdf/scripts/convert.py 'https://www.bilibili.com/video/BV1rH4y1R7Rk' --output /absolute/path/to/new-result
uv run skills/bilibili-drum-score-to-pdf/scripts/convert.py /absolute/path/to/video.mp4 --output /absolute/path/to/new-result
```

使用新的空目录，检查 stdout JSON 和 `manifest.json`。`success` 表示所有空间谱行都选到了完整干净原图，PDF 在行间分页。`waiting` 给出时间、截图和简单原因，请提供更好的视频后运行新任务。`failed` 给出脱敏诊断。匿名获取失败且目录仅含失败 manifest 时，可用原命令重试。

结果目录包含 `score.pdf`、独立标题图、逐行 RGB 原裁剪与灰度打印图、原视频帧和来源记录。每行可按 timestamp、bbox 和 original_image 核对。打印前逐页检查符头、符杆、细小记号与首尾。

## 支持范围

支持固定比例、白底、多行、固定窗口或单向向上推进的长谱，相邻窗口需有至少两条完整五线重叠。标题与速度从首张稳定谱面独立保留。重复段落按空间位置保留；半行等到完整出现才收录。

光标与固定屏幕遮挡只影响候选选择。程序不擦除光标，不拼接像素、不补绘、不识别重排音符。原谱彩色记号只转灰度。没有干净完整观察时返回等待。

低于 150 effective DPI 的谱行拒绝打印。高 DPI 仍需人工核对清晰度。任意遮挡、比例变化、倒退、无重叠的大跳跃以及快速推进造成的几何歧义不保证支持。稀疏采样无法证明两次观察之间没有换谱。

## 验证与维护

```sh
uv run --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt python -m unittest discover -s tests -v
```

测试还需要 Poppler 的 `pdfinfo` 与 `pdftoppm`。架构、输入安全、资源限额和边界见 [architecture](docs/architecture.md)，真实 URL 双跑与逐行来源验收见 [verification](docs/verification.md)。随仓库交付的 [SKILL.md](skills/bilibili-drum-score-to-pdf/SKILL.md) 使用同一入口。

移动窗口核心三个模块合计不得超过 500 行；依赖防火墙测试防止引入已删除的恢复模块。历史方案通过 Git history 查看。

## Agent-first 试验路径

固定本地谱面可通过同一入口执行 prepare、submit、export 和 replay。Agent 阅读原图、相邻对照图及原生细节并提交结构化选择，脚本验证并从真实原帧导出。默认流程保持现有 moving viewport。操作、协议和当前限制见 [Agent workflow](docs/agents/agent-workflow.md)。
