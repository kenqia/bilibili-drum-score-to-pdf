<p align="center">
  <img src="docs/images/readme-hero.png" alt="B站鼓谱视频转 PDF · 把视频里的鼓谱，带到鼓架前。" width="100%">
</p>

<p align="center">
  从已有鼓谱的视频，到可以打印的 A4 乐谱。<br>
  给视觉 Agent 一个链接，完成采集、清理、重排与逐页检查。
</p>

<p align="center">
  <a href="https://github.com/kenqia/bilibili-drum-score-to-pdf/actions/workflows/offline.yml"><img src="https://github.com/kenqia/bilibili-drum-score-to-pdf/actions/workflows/offline.yml/badge.svg" alt="离线验证状态"></a>
  <img src="https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square" alt="Python 3.12">
  <img src="https://img.shields.io/badge/output-A4%20PDF-D5A45B?style=flat-square" alt="输出 A4 PDF">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-B9BDB4?style=flat-square" alt="代码使用 MIT 许可证"></a>
</p>

<p align="center">
  <a href="#开始使用">开始使用</a> ·
  <a href="#看看结果">看看结果</a> ·
  <a href="#适合什么视频">支持范围</a> ·
  <a href="llms.txt">给 AI 的检索入口 / For agents</a> ·
  <a href="docs/README.md">文档导航</a>
</p>

## 把时间留给练习

练一首歌，不该先花时间拖进度条、截屏、裁图，再把零散的谱面拼起来。

这个项目把这段工作交给视觉 Agent。它自动将纵向滚动鼓谱合成长截图，直接按完整谱行等比排成 A4，可对确认不含记谱、标题和署名的区域局部去水印。标题、速度、拍号和后续重复出现的音乐保留。Agent 整体查看长图及最终每一页，不逐符号校对。重绘和矢量只在明确要求时启用。

它是一个 **Agent Skill**。本地脚本处理视频、来源记录和排版，宿主 Agent 负责视觉判断及可选生图。历史版本有 Codex 整曲验证记录；当前长截图主线的实测范围见验证记录。

## 看看结果

![从视频谱面、完整谱行到 A4 PDF 的流程演示](docs/images/workflow.gif)

<p align="center"><sub>12 秒静音循环 · 旧重绘路线的已保存真实样本 · 历史流程演示</sub></p>

示例为实际转换并逐页检查的《鲜花》，演唱者为回春丹。原视频水印署名「帅气迷人的小磊子」，谱面署名「JIAN磊」。[查看原视频](https://www.bilibili.com/video/BV1Yw4m1Y7YH) · [下载三页 A4 PDF](docs/media/readme/assets/xianhua/xianhua-A4.pdf) · [查看来源与审阅记录](docs/media/readme/assets/xianhua/provenance.json)。音乐与谱面权利归原权利人。

<details>
<summary>查看静态流程图与实际 PDF 页面</summary>

![视频到打印谱的静态流程展示](docs/images/workflow-poster.png)

下面是《鲜花》PDF 的第一页。整份输出共三页，包含 27 条完整谱行，覆盖第 1–113 小节并保留反复结构。

<img src="docs/media/readme/assets/xianhua/page-1.png" alt="鲜花 A4 PDF 第一页，保留标题、速度与完整谱行" width="520">

本次实际查看了原生来源、四组宿主重绘结果和最终全部三页。谱行接续通过小节号与重叠谱行核对。

</details>

## 开始使用

### 1. 安装后这样用

在宿主输入框中选中 [$bilibili-drum-score-to-pdf](skills/bilibili-drum-score-to-pdf/SKILL.md)，然后粘贴视频链接。例如在 Codex 中输入 `$`，从可用 Skill 中选择本项目，再发送：

```text
$bilibili-drum-score-to-pdf

https://www.bilibili.com/video/BV1Yw4m1Y7YH/

整理成 A4 PDF，保存到我指定的目录。
```

上面的 Skill 链接用于查看指令文件；实际选择发生在宿主输入框中，无需复制任何人的本地安装路径。只提供 Skill 和链接也可以启动默认 PDF 流程。未指定保存位置时，Agent 在当前工作目录下创建独立任务目录，交付时报告绝对路径。

也可以提供本地视频的绝对路径。公开 B站链接支持 `?p=2` 分 P。采集、整理、完整谱行排版和逐页检查由 Skill 指导 Agent 执行，用户无需填写任务 JSON。该链接也是上方《鲜花》展示的实际来源。

### 2. 还没安装？

把下面这段话发给有文件读写和脚本运行能力的 Agent：

```text
请安装这个仓库中的 bilibili-drum-score-to-pdf Skill：
https://github.com/kenqia/bilibili-drum-score-to-pdf

先读取 docs/install.md，将 skills/bilibili-drum-score-to-pdf
整个目录安装到当前宿主能发现 Skill 的位置。
请一起保留 SKILL.md、scripts/、references/ 和 LICENSE，
检查运行依赖；更新已有安装时先保留可恢复副本。

安装后确认它出现在宿主的技能列表或选择器中，
并报告安装位置、源码版本和验证结果。
```

对外 Skill 是自包含目录，执行所需协议随 `references/` 一起分发，运行时无需源码仓库的 `docs/`。依赖 Python 3.12、uv、FFmpeg、ffprobe 和 Poppler；宿主需要实际查看原生图片及 PDF 页面。代码开源，宿主 AI 服务可能收费。

手动安装、受管理安装与回滚见[安装指南](docs/install.md)。不同宿主的发现位置和调用界面不同，其他宿主尚未完成整曲验收。

### 3. 怎样确认安装成功？

让 Agent 核对以下事项，而不只是报告“文件已下载”：

- 宿主技能列表或选择器能找到并选中 `bilibili-drum-score-to-pdf`。未出现时重新加载或重启宿主后再核对。
- 已安装目录内的 `SKILL.md`、`scripts/convert.py` 和 `references/stage-recovery-layout.md` 存在且可读。
- 在安装目录中运行下面的帮助命令，退出成功并显示 `stage`、`export`、`review-pdf` 等操作；同时核对 FFmpeg、ffprobe、Poppler 与宿主看图能力。

```sh
uv run --python 3.12 --isolated --with-requirements scripts/requirements.txt \
  python scripts/convert.py --help
```

这些检查证明安装和入口可用。具体视频仍需通过来源检查和最终全部页面审阅，才能交付完整 PDF。

### 4. 开发者入口

<details>
<summary>从命令行准备任务、理解产物与恢复</summary>

在源码仓库根目录执行：

```sh
uv run --python 3.12 --isolated --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt \
  python skills/bilibili-drum-score-to-pdf/scripts/convert.py \
  /absolute/path/to/video.mp4 --output /absolute/path/to/new-task
```

替换两个绝对路径，输出使用新的任务目录。安装目录中使用同一命令的 `scripts/` 相对路径。该命令准备任务；随后 `stage` 自动生成长截图。Agent 整体查看长图及首尾，通过 `review-longshot` 记录谱名和一份备注，再按连续条带原图分页、A4 导出及全部页面与切口检查，保持页内原行距。自动分页在最多缩小 10% 且字号符合门槛时尝试减少页数，仍需查看实际打印字号和分页切口；手动指定切口可保留原尺寸。蓝标、水印和局部模糊不阻止交付。只有阶段返回 `complete` 才交付。

PDF 位于任务目录的 `exports/<revision>/<谱名>.pdf`。原视频保存在相邻的独立来源目录，原截图和历史结果保留，恢复检查来源与材料 hash。操作请求见[命令入口](skills/bilibili-drum-score-to-pdf/references/reconstruction-entry.md)，正常推进与恢复见[阶段指南](skills/bilibili-drum-score-to-pdf/references/stage-recovery-layout.md)。

</details>

## 它怎样处理一份谱

| 环节 | 实际处理 |
| --- | --- |
| 收集谱面 | 流式采样、估计垂直位移并合成长截图，保存实际时间戳与 hash；自动按完整谱行切分。 |
| 局部去水印 | 只修改实际确认安全的区域，保留原图及记录；重叠记谱或署名的水印保留。 |
| 整理打印 | 按来源比例统一排版，只在完整谱行之间分页；可调整边距、最小行距和目标页数。 |
| 检查交付 | Agent 查看全部最终页面，再批准当前输出版本。来源、修正与历史文件保留。 |

轻微模糊、底色和残留水印可保留。明显缺行或重复先修复拼接，严重遮挡优先从原视频补采；仍无法恢复时说明限制，不自动猜符号。原图直排避免重绘新增的变形，仍未经逐符号校对。用户明确要求时可选择重绘或矢量，轮廓转描不等于音乐识别。分页优先保留完整单元和统一比例，目标页数只作结果对照。

## 适合什么视频

| 输入 | 当前支持情况 |
| --- | --- |
| 固定比例、白底多行的纵向滚谱 | 长截图主线首版范围，优先适配停驻后向上推进。 |
| 公开 B站 BV 链接、本地鼓谱视频 | 共用任务入口；链接以匿名方式获取。 |
| 水印、播放高亮或局部模糊 | 可保留并直排；安全区域可局部去水印，严重遮挡优先原视频补采。 |
| 横向滚动、比例变化或复杂翻页 | 不纳入首版。 |
| 只有演奏画面、没有谱面的视频 | 不支持从音频或演奏动作生成鼓谱。 |

## 有哪些验证

已有《KiLLKiSS》《可惜没如果（新版）》和《小星星》的真实 PDF 验收记录，包含宿主生图、来源证据和全部页面查看；另有 KiLLKiSS 强制矢量与遮挡修复记录。[查看验证范围与证据](docs/verification.md)。

这些是历史指定样本的结果，不代表长截图主线已经完成新的真实生图或整曲验收。宿主、输入布局和原始清晰度都会影响可交付结果。

运行仓库验证：

```sh
uv run --python 3.12 --isolated --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt \
  python -m unittest discover -s tests -v
```

CI 验证合成与确定性产物，不调用宿主模型，不证明音乐准确率。模型成本未知时记录为 `null`。

## 继续阅读与反馈

| 你想做什么 | 从这里开始 |
| --- | --- |
| 安装、更新或回滚 | [安装指南](docs/install.md) |
| 让 AI 判断项目是否适用 | [AI 检索摘要](llms.txt) · [Skill 规范入口](skills/bilibili-drum-score-to-pdf/SKILL.md) |
| 运行与恢复任务 | [阶段指南](docs/agents/stage-recovery-layout.md) · [命令参数](docs/agents/reconstruction-entry.md) |
| 理解实现、贡献改动 | [文档导航](docs/README.md) · [架构](docs/architecture.md) · [项目工作约定](AGENTS.md) |
| 报告问题或提出建议 | [GitHub Issues](https://github.com/kenqia/bilibili-drum-score-to-pdf/issues) |

反馈时请附公开来源或脱敏的复现材料、宿主、失败阶段和预期结果。不要提交 Cookie、认证文件或带签名的媒体地址。

## 许可证与示例署名

代码与原创文档采用 [MIT 许可证](LICENSE)。音乐、谱面及其衍生展示不属于本项目的 MIT 授权范围，权利归原权利人；[展示素材说明](docs/media/readme/README.md)保留来源与署名。
