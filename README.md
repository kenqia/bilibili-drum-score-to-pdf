# B站动态鼓谱转 PDF

一个可检查的 Codex skill 文件包：输入 B站动态架子鼓谱链接或本地视频，将已有谱面整理成可打印 PDF。

## 当前状态

实现候选已提供，最终审查修复后的 35 项统一入口测试通过；《七里香》高清整曲、全部拼接位置和打印可读性仍待验收。#7 与父规格 #1 未完成。

仓库已提供可检查的 [skill 文件包](skills/bilibili-drum-score-to-pdf/SKILL.md)。当前支持白底、多行、固定或纵向推进谱面的本地视频，自动裁剪完整谱行并生成 A4 纵向 PDF。PDF 保留视频中可提供的标题、速度和拍号，源视频对应记录保存在 `manifest.json`。

```sh
uv run skills/bilibili-drum-score-to-pdf/scripts/convert.py /absolute/path/to/video.mp4 --output /absolute/path/to/result
```

命令需要 `ffmpeg`、`ffprobe`、`uv` 和 Python 3.12 或更高版本。`uv` 在独立环境运行依赖。stdout 输出结构化 JSON，stderr 输出进度；`status` 区分成功、等待确认和失败。

入口采样完整视频并核查真实末帧。纵向跳行和滚动只按相邻窗口的唯一有序重叠与向上位移接续；同一处停留画面只保留一次，后续再次出现的谱段仍保留。上下边缘残行不会直接进入 PDF。`seams` 保存每个接续位置的前后截图与时间，`boundaries` 保存开头和结尾。缺少唯一重叠或首尾残行未恢复时，返回编号疑点和未确认候选谱行，不声称完整。输出优先选择同一谱行无浅蓝竖块遮挡的真实整行画面，再按清晰度择优。原图、观察时间和质量报告保留；原谱彩色记号只转灰度，不擦除、补绘或用放大伪造细节。仅有后续干净帧不足以证明光标下的内容相同。连续遮挡观察需保持同位置，光标移动后的真实可见部分必须互补覆盖所有隐藏区域，并与最终无遮挡整行一致，否则返回 `cursor_occlusion`。前后相同的干净画面也不能证明中间固定位置不透明遮挡的内容。`cursor_recoveries`、`cursor_followups` 保留证据图与时间。当前不会安装 skill 或修改 Codex 配置。

细小记号变化也会触发内容疑点。短暂模糊先寻找后续实际清晰帧；只有同位置、同内容的清晰两端及每个中间原图都满足局部检查才恢复，并保留 `recoveries` 证据。无法确认的转换和模糊首尾仍等待。检查范围和像素门槛见[验证记录](docs/verification.md)，不以这个启发式替代整曲逐页核查。

## B站链接输入

同一命令接受 HTTPS BV 视频链接，可用 `?p=2` 指定分 P，省略时选择第一 P。

```sh
timeout 120s uv run skills/bilibili-drum-score-to-pdf/scripts/convert.py 'https://www.bilibili.com/video/BV1b5411x7Ku' --output /absolute/path/to/new-result
```

入口只请求公开匿名接口，不登录或读取 Cookie、认证、密钥。取得的视频留在结果目录，随后执行同一个本地转换流程。`manifest.json` 保存规范 BV 链接、分 P、CID、接口画质代码及本地探测的实际宽高，媒体签名地址不会进入记录或日志。

网络、访问限制、接口变化或不支持的媒体地址会立即停止。WSL 中的 `timeout 120s` 给整次链接尝试设置外部时限；若退出码为 124 且尚无 JSON，按网络超时处理并改用本地视频，不继续重试。画质不足时报告实际分辨率，请提供清晰本地视频并重新运行本地命令。请求 1080P 不等于取得 1080P，元数据尺寸也不能代替实际视频尺寸。下载只支持单文件 MP4、HTTPS B站媒体域名，不跟随重定向；因此部分正常 CDN 变化也可能触发本地兜底。

[维护依据与停止条件](skills/bilibili-drum-score-to-pdf/references/anonymous-input.md)说明公开接口限制。

## 疑点回答后继续

等待时返回稳定编号、截图、源视频时间和可选处理。保留结果目录，在当前 Codex 聊天中明确确认拼接、重复段落、提供完整谱行图片，或接受标有缺失位置的结果。Codex 把明确回答转为本地答案文件，不要求用户写 JSON。

```sh
uv run skills/bilibili-drum-score-to-pdf/scripts/convert.py --resume /absolute/path/to/result --answers /absolute/path/to/answers.json
```

不提供 `--answers` 会保持已有状态。未知选择、含糊回答或无效补图不能解决疑点。恢复会校验原视频和进度，再重放到视频末尾或下一个问题，保留之前的确认。接受缺失时 PDF 在对应位置插入标记，`complete` 为 false，附限制说明。原视频或状态损坏时保留原目录并报告失败。

新转换必须使用空目录；恢复使用 `--resume`，不会覆盖已有任务。

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
