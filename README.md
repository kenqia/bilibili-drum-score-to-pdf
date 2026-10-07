# B站动态鼓谱转 PDF

一个可检查的 Codex skill 文件包：输入 B站动态架子鼓谱链接或本地视频，将已有谱面整理成可打印 PDF。当前定位为“同模板真实可用 / internal beta”。

## 快速开始

在 Windows/WSL 的 Linux 环境中安装 Python 3.12+、uv、ffmpeg。验证测试另需 Poppler。依赖由 uv 在独立环境运行，无需登录 B站或配置 Cookie。

```sh
git clone https://github.com/kenqia/bilibili-drum-score-to-pdf.git
cd bilibili-drum-score-to-pdf
uv run skills/bilibili-drum-score-to-pdf/scripts/convert.py 'https://www.bilibili.com/video/BV1rH4y1R7Rk' --output /absolute/path/to/new-result
```

请使用新的空目录。查看 stdout JSON 的 `status` 和结果目录的 `manifest.json`：`success` 后核对 `complete`、`score.pdf` 及全部拼接证据；`waiting` 按编号疑点确认；`failed` 查看脱敏原因，可改用清晰本地视频。接受缺失后输出的 `complete=false` 不代表完整还原。打印前仍需逐页核对细小音符和首尾。

五分钟真实样本在测试环境中约需 19 分钟，不承诺固定速度。本版适合白底、多行、纵向向上推进且类似已验收样本的布局。高 DPI 不等于清晰，长期中央遮挡尚未支持完整滚动恢复。完整边界和后续工作见 [beta 限制](docs/beta-limitations.md)。

## 当前状态

2026-10-07，真实[《可惜没如果（新版）》](https://www.bilibili.com/video/BV1rH4y1R7Rk)已从统一 URL 入口匿名取得 1080p，并输出完整 12 行、2 页 A4 PDF。两次整曲内容与证据一致，107 项全量测试通过，全部页面和滚动位置已核查。详见[本轮实现状态](docs/implementation-status.md)。本轮结论针对这一真实视频，其他布局与《七里香》高清整曲仍需单独验收。

仓库已提供可检查的 [skill 文件包](skills/bilibili-drum-score-to-pdf/SKILL.md)。当前支持白底、多行、固定或纵向推进谱面的本地视频，自动裁剪完整谱行并生成 A4 纵向 PDF。PDF 保留视频中可提供的标题、速度和拍号，源视频对应记录保存在 `manifest.json`。

```sh
uv run skills/bilibili-drum-score-to-pdf/scripts/convert.py /absolute/path/to/video.mp4 --output /absolute/path/to/result
```

命令需要 `ffmpeg`、`ffprobe`、`uv` 和 Python 3.12 或更高版本。`uv` 在独立环境运行依赖。stdout 输出结构化 JSON，stderr 输出进度；`status` 区分成功、等待确认和失败。

几乎完全均匀的纯色卡片，以及清晰、均匀背景的文字标题卡和结束卡，可作为无谱面边缘忽略。检查文字清晰度及前景形状，任一长水平线都阻止忽略，包括与背景灰度差超过 2 级的微弱线条；清晰标题文字不能抵消残谱信号。局部五线和残行继续进入疑点。纯色卡片要求各 RGB 通道全图极差不超过 2 级；渐变、模糊或无法分类的边缘仍需确认，中段卡片不会被忽略。`ignored_edges` 保存忽略边缘的时间范围、原图与分类规则；`boundaries.end` 保留实际最后一帧，另可从忽略记录核查结束卡。全片没有完整谱行不得成功。此规则只识别均匀纯色卡和清晰文字卡，不能证明任意图片封面没有隐藏谱面。

入口采样完整视频并核查真实末帧。纵向跳行和滚动只按相邻窗口的唯一有序重叠与向上位移接续；同一处停留画面只保留一次，后续再次出现的谱段仍保留。上下边缘残行不会直接进入 PDF。`seams` 保存每个接续位置的前后截图与时间，`boundaries` 保存开头和结尾。缺少唯一重叠或首尾残行未恢复时，返回编号疑点和未确认候选谱行，不声称完整。

输出优先选择同一谱行无浅蓝竖块遮挡的真实整行画面，再优先选择下边界已有后续五线支持的裁剪，最后按清晰度择优。首行候选须保留已观察到的标题和速度。原图、观察时间和质量报告保留；裁剪空隙与末行边界也检查彩色墨迹，亮黄色等灰度较浅的记号不能被当作空白裁掉。原谱彩色记号只转灰度，不擦除、补绘或用放大伪造细节。

仅有后续干净帧不足以证明光标下的内容相同。停留画面中的光标观察按五线锚点约束位置。所有隐藏区域必须由光标移动后真实暴露的像素互补覆盖，并与实际无遮挡整行一致，否则返回 `cursor_occlusion`。完整互补记录也可核对此前同位置的实际无遮挡整行。若光标跨越滚动，只有唯一有序重叠、至少两条匹配行、至少一条双方无遮挡行和共同向上位移均成立时，比较坐标才跟随滚动；位移至少两个五线间距，各行位移相差最多 2 像素。未知像素仍保持未知，须由后续真实光标观察暴露，不能仅凭滚动或干净端点假定内容相同。前后相同的干净画面也不能证明中间固定位置不透明遮挡的内容。`cursor_recoveries`、`cursor_followups` 保留证据图与时间。当前不会安装 skill 或修改 Codex 配置。

谱行比较支持受限的观察配准。最多搜索横纵各 2 像素平移，候选缩放只使用原尺寸与裁剪尺寸比例，宽度差不超过 0.5% 且高度差不超过 3 像素。候选先最小化可见墨迹的全部差异，再比较远离对应墨迹的差异点。最优同得分拟合必须唯一，之后仍逐点检查可见墨迹，不能用整行变化百分比忽略小音符；边缘可见记号也不得通过配准裁掉。停留画面的五线锚点位移须小于半个五线间距，空白裁剪边界变化不代表五线移动。跨滚动的光标比较另需上述独立位移证明，缺少互补覆盖或配准不唯一仍等待。配准只改变比较坐标，PDF 与 `original_image` 保留所选真实帧的原生像素。`cursor_recoveries.motions` 保存跨滚动的前后窗口、匹配行和五线锚点，`seams.registrations` 保存拼接比较变换。合成验证覆盖 2 像素纵向位移、0.2% 缩放、0.35 像素抗锯齿与二次 H.264 编码，真实 1080p 视频的修复与验收记录见[《可惜没如果》验证记录](docs/verification-real-bilibili.md)。这些观察不代表任意缩放、快速滚动或频道输入均适用。

细小记号变化也会触发内容疑点。短暂模糊先寻找后续实际清晰帧；只有同位置、同内容的清晰两端及每个中间原图都满足局部检查才恢复，并保留 `recoveries` 证据。无法确认的转换和模糊首尾仍等待。检查范围和像素门槛见[验证记录](docs/verification.md)，不以这个启发式替代整曲逐页核查。

## B站链接输入

同一命令接受 HTTPS BV 视频链接，可用 `?p=2` 指定分 P，省略时选择第一 P。

```sh
uv run skills/bilibili-drum-score-to-pdf/scripts/convert.py 'https://www.bilibili.com/video/BV1b5411x7Ku' --output /absolute/path/to/new-result
```

入口使用固定版本 yt-dlp 的内置 Bilibili extractor 匿名枚举格式，不读取用户配置、Cookie、浏览器登录态、netrc 或插件。按原生分辨率、H.264 编码兼容性、帧率和码率选择可解码视频轨，优先 video-only。只有没有独立视频轨时才取含音频的单文件，并记录 `origin.single_file_fallback`。不会另下音轨或混流。

下载先进入结果目录之外的 staging。ffprobe 测量尺寸、编码和帧率，ffmpeg 验证首帧可解码后才发布源视频，再执行本地谱面还原。`manifest.json` 保存规范 BV 链接、分 P、后端版本、选中格式 ID 与实测参数。签名媒体地址、代理认证和后端原始异常不进入输出或记录。

获取工作进程默认最多运行 30 分钟，`--acquisition-timeout 120` 可缩短总时限，覆盖 DNS、接口请求、下载、探测、目标文件复制和进程退出；连接超时 20 秒，元数据的压缩体与解压体各限 2 MiB，视频上限 2 GiB。最多枚举 3 个候选格式，每个格式最多使用 2 个官方备用地址；候选过大、不安全地址或实测分辨率与标记不符目前会提前终止，尚未保证继续下一候选，详见 beta 限制。超时、Ctrl+C 或 SIGTERM 会停止获取进程组并清理本次 staging。Linux 上强杀 CLI 也会停止获取进程组，最终目录不会留下下载 partial；强杀可能留下结果目录之外的 staging，不会自动清理未知文件。获取时限与后续本地转换时限分开，本地 ffprobe 最多 30 秒、采样解码最多 600 秒、末帧解码最多 60 秒；谱面分析和 PDF 排版没有整体时限。媒体地址及每次重定向都检查 HTTPS、无 URL 凭据与公开目标，并在实际连接时固定已验证 IP。建连失败会顺序尝试其余已验证公开地址，IPv6 失败不阻止 IPv4。extractor 请求保留 yt-dlp 默认请求头，读取有界 gzip 响应。环境代理仍可使用。HTTP CONNECT 代理向固定目标 IP 建隧道，TLS 校验原域名。

访问限制、格式失败、不可解码或实测分辨率低于格式标记时返回脱敏原因和本地视频兜底。匿名接口不能保证 1080p，元数据尺寸不能代替实际尺寸。`error.failure_stage`、`error.backend_error_type` 和可用的 `http_status` 提供脱敏获取诊断，不输出原始异常或签名地址。仅获取失败时，目录只含标记 `phase=acquisition` 的失败 `manifest.json`，可用原命令在同一目录重试，也可换清晰本地视频。未知文件、已有源视频或转换结果会阻止重试，需选择空目录或对已有任务使用 `--resume`。

[维护依据与停止条件](skills/bilibili-drum-score-to-pdf/references/anonymous-input.md)说明公开接口限制。

## 疑点回答后继续

等待时返回稳定编号、截图、源视频时间和可选处理。保留结果目录，在当前 Codex 聊天中明确确认拼接、重复段落、提供完整谱行图片，或接受标有缺失位置的结果。Codex 把明确回答转为本地答案文件，不要求用户写 JSON。

```sh
uv run skills/bilibili-drum-score-to-pdf/scripts/convert.py --resume /absolute/path/to/result --answers /absolute/path/to/answers.json
```

不提供 `--answers` 会保持已有状态。未知选择、含糊回答或无效补图不能解决疑点。恢复会校验原视频和进度，再重放到视频末尾或下一个问题，保留之前的确认。接受缺失时 PDF 在对应位置插入标记，`complete` 为 false，附限制说明。原视频或状态损坏时保留原目录并报告失败。

新转换使用空目录，或仅含本入口 acquisition-only 失败诊断的目录；恢复使用 `--resume`，不会覆盖已有任务。

## 验证

```sh
uv run --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt python -m unittest discover -s tests -v
```

验收测试通过统一命令调用转换，使用独立绘制的谱面和真实编码视频，检查 A4、整行分页、标题与源视频时间、低清失败、邻接重叠、真正重复段落、连续滚动、首尾疑点、移动与持续光标、原谱蓝色休止记号保留。测试需要 Poppler 的 `pdfinfo` 与 `pdftoppm`。

[验证与交付记录](docs/verification.md)列出实测结果、工具版本和复核命令。[需求规格](docs/spec.md)列出整曲验收标准，[领域术语](GLOSSARY.md)区分重复截图和重复段落。固定和滚动合成视频的验证不代表真实整曲已经通过。

## 第一版样本

[《七里香 周杰伦 动态鼓谱》](https://www.bilibili.com/video/BV1b5411x7Ku)，时长 4 分 57 秒。已读取完整匿名视频并观察到 29 次约一谱行的向上位移，实际画面为 640×360。该视频只用于布局研究和低清拒绝验证；没有清晰本地样本前，整曲顺序与打印质量仍未验收。

第一版建议面向白底、多行、纵向推进的谱面。具体适配结果以整曲测试为准，不承诺任意视频布局。

## 项目约定

优先复用已有工具和成熟依赖。新增依赖在独立环境验证，不修改全局 Python 环境。工程技能配置已完成。项目约定见 [AGENTS.md](AGENTS.md)，具体规则见 [docs/agents](docs/agents)。后续工程技能从这些文档读取 GitHub Issues、分诊标签和领域文档约定。可直接修改 docs/agents 中的文档；只有切换 issue tracker 或重新初始化时才需要重跑 setup。

常规采样按 10 秒批次迭代分析并释放临时 PNG，保留上一可读参考及必要证据；不先将完整视频导出成 PNG。各批累计解码进程时间最多 600 秒，末帧核查另限 60 秒，图像分析和 PDF 排版另计。资源验证见 [有界解码记录](docs/verification-bounded-decode.md)。
