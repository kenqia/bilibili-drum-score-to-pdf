# B站鼓谱视频转 PDF

把视频中已有的纵向滚动鼓谱整理成 A4 PDF。支持本地 CLI、Python 和匿名网站。程序保留谱面图像，不调用模型；自动完成不代表音乐已校对。

## 开始使用

需要 Python 3.12 或更新版本，以及 `ffmpeg`、`ffprobe`、`pdftoppm`。公开 B站链接另需[固定的 BBDownNext 2.3.0 有界构建](docs/install.md#安装公开链接解析器)。当前本地验证使用 Python 3.12。

```sh
python3.12 -m venv .venv
.venv/bin/pip install .
.venv/bin/drum-score 'https://www.bilibili.com/video/BV1rH4y1R7Rk?p=1' --output /absolute/path/new-result
```

也可将链接换成本地视频路径。输出目录必须不存在。成功目录包含 `score.pdf`、全部页面预览、`manifest.json` 及本地实验所需的原生帧和长图。错误返回脱敏 JSON，退出码为 2。参见[安装指南](docs/install.md)和[转换契约](docs/script-product/conversion.md)。

## 匿名网站

```sh
.venv/bin/pip install '.[web]'
.venv/bin/drum-score-web --data-root /absolute/path/drum-score-data --host 127.0.0.1 --port 8000
```

在另一个终端启动 `.venv/bin/drum-score-worker --data-root /absolute/path/drum-score-data`，打开 [本地网页](http://127.0.0.1:8000)。保存完整任务链接，完成后查看全部预览并下载 PDF。网站结果保留 24 小时，视频、原生帧及长图在任务结束后清理。详见[网站运行与存储规则](docs/script-product/website.md)。

停服备份、核验和恢复见[维护指南](docs/script-product/maintenance.md)，独立发行环境、systemd、nginx 及回滚见[部署指南](docs/script-product/deployment.md)。

网站已部署到 [drum.kenqia.top](https://drum.kenqia.top/)。2026-10-22 的腾讯云直连完整转换、资源、恢复及公网浏览器验收见[BBDownNext 接入记录](docs/experiments/2026-10-22-bbdown-integration.md)。

## 适合什么视频

首版面向白底、固定比例、纵向向上推进的已有鼓谱。保留完整谱行、原行距、相关记号与后续重复音乐。无法确认安全去除的水印、模糊和播放标记保留。检测到缺段、配准歧义或不支持的翻页时明确失败；程序不能自动识别所有谱面问题。

不从演奏音频或动作生成乐谱。横移、缩放、复杂翻页不属于已验证范围。不提供重绘、矢量转描、MIDI 或 Agent 审批入口。

## 历史示例

![历史流程演示](docs/images/workflow.gif)

此示例来自旧重绘路线，保留作为历史证据。《鲜花》演唱者为回春丹；原视频水印署名「帅气迷人的小磊子」，谱面署名「JIAN磊」。[原视频](https://www.bilibili.com/video/BV1Yw4m1Y7YH)、[三页历史 PDF](docs/media/readme/assets/xianhua/xianhua-A4.pdf)和[来源记录](docs/media/readme/assets/xianhua/provenance.json)不代表当前程序的新验收。

旧 Skill 分发及审批协议已退役；旧实现通过 Git history 获取，旧任务不自动迁移，已安装的 Skill 不会被本仓库卸载。

## 开发与证据

[架构](docs/architecture.md)、[验证入口及实际结果](docs/verification.md)、[领域术语](GLOSSARY.md)和[文档导航](docs/README.md)说明当前产品。历史实验保存在 `docs/experiments/` 和 `experiments/`，保护原始来源、实际 PTS 和 hash。合成测试不替代真实谱面与全部页面审阅。

代码与文档使用 [MIT](LICENSE)；音乐、谱面和派生示例素材权利归原权利人，见[素材说明](docs/media/readme/README.md)。
