# B站动态鼓谱转 PDF

一个计划中的 Codex skill：输入 B站动态架子鼓谱链接或本地视频，将已有谱面整理成可打印 PDF。

## 当前状态

仓库已提供可检查的 [skill 文件包](skills/bilibili-drum-score-to-pdf/SKILL.md)。当前支持白底、多行、固定谱面的本地视频，自动裁剪完整谱行并生成 A4 纵向 PDF。PDF 保留视频中可提供的标题、速度和拍号，源视频对应记录保存在 `manifest.json`。

```sh
uv run skills/bilibili-drum-score-to-pdf/scripts/convert.py /absolute/path/to/video.mp4 --output /absolute/path/to/result
```

命令需要 `ffmpeg`、`ffprobe`、`uv` 和 Python 3.12 或更高版本。`uv` 在独立环境运行依赖。stdout 输出结构化 JSON，stderr 输出进度；`status` 区分成功、等待确认和失败。

固定谱面检查会采样完整视频及末尾。发现谱面变化时提供编号证据并返回等待状态，不将一个窗口当作整曲。纵向推进恢复、光标处理和疑点回答后继续由后续切片完成。当前不会安装 skill 或修改 Codex 配置。

## B站链接输入

同一命令接受 HTTPS BV 视频链接，可用 `?p=2` 指定分 P，省略时选择第一 P。

```sh
timeout 120s uv run skills/bilibili-drum-score-to-pdf/scripts/convert.py 'https://www.bilibili.com/video/BV1b5411x7Ku' --output /absolute/path/to/new-result
```

入口只请求公开匿名接口，不登录或读取 Cookie、认证、密钥。取得的视频留在结果目录，随后执行同一个本地转换流程。`manifest.json` 保存规范 BV 链接、分 P、CID、接口画质代码及本地探测的实际宽高，媒体签名地址不会进入记录或日志。

网络、访问限制、接口变化或不支持的媒体地址会立即停止。WSL 中的 `timeout 120s` 给整次链接尝试设置外部时限；若退出码为 124 且尚无 JSON，按网络超时处理并改用本地视频，不继续重试。画质不足时报告实际分辨率，请提供清晰本地视频并重新运行本地命令。请求 1080P 不等于取得 1080P，元数据尺寸也不能代替实际视频尺寸。下载只支持单文件 MP4、HTTPS B站媒体域名，不跟随重定向；因此部分正常 CDN 变化也可能触发本地兜底。

[维护依据与停止条件](skills/bilibili-drum-score-to-pdf/references/anonymous-input.md)说明公开接口限制。

## 验证

```sh
uv run --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt python -m unittest discover -s tests -v
```

验收测试通过统一命令调用转换，使用独立绘制的谱面和真实编码视频，检查 A4、整行分页、标题与源视频时间、低清失败以及动态输入疑点。测试需要 Poppler 的 `pdfinfo` 与 `pdftoppm`。

[需求规格](docs/spec.md)列出整曲验收标准，[领域术语](GLOSSARY.md)区分重复截图和重复段落。固定合成视频的验证不代表真实整曲已经通过。

## 第一版样本

[《七里香 周杰伦 动态鼓谱》](https://www.bilibili.com/video/BV1b5411x7Ku)，时长 4 分 57 秒。已观察三张匿名采样帧，实际画面为 640×360；这不足以证明整曲完整或达到打印清晰度。

第一版建议面向白底、多行、纵向推进的谱面。具体适配结果以整曲测试为准，不承诺任意视频布局。

## 项目约定

优先复用已有工具和成熟依赖。新增依赖在独立环境验证，不修改全局 Python 环境。工程技能配置已完成。项目约定见 [AGENTS.md](AGENTS.md)，具体规则见 [docs/agents](docs/agents)。后续工程技能从这些文档读取 GitHub Issues、分诊标签和领域文档约定。可直接修改 docs/agents 中的文档；只有切换 issue tracker 或重新初始化时才需要重跑 setup。
