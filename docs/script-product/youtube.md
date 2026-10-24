# YouTube 单视频获取

程序、CLI 和网站使用 yt-dlp 获取匿名 YouTube 单视频。B站继续使用 BBDownNext，独立 Skill 不变。此能力已加入本地代码，尚未部署到正式网站。网络可达不代表 YouTube 一定允许匿名下载，机器人验证会导致任务失败。

## 输入范围

接受 HTTPS `youtube.com/watch?v=…`、`www.youtube.com/watch?v=…`、`youtu.be/…` 和 `youtube.com/shorts/…`。视频 ID 必须是 11 位合法字符，拒绝重复 `v`、其他端口、用户信息和仿冒主机。规范来源统一记录为 `https://www.youtube.com/watch?v=视频ID`。

播放列表参数不会创建批量任务，时间戳不裁剪视频，始终获取整条来源。拒绝直播、直播回放标记、需要登录、会员或年龄验证的来源。网页可从分享文案提取链接，Python 和 CLI 接收链接本身。保留旧错误码 `invalid_bilibili_url` 以兼容调用方，提示文字已覆盖两个平台。

## 安装与代理

程序环境固定安装 `yt-dlp==2026.10.21` 和 `yt-dlp-ejs==0.8.0`。YouTube 另需 PATH 中的 Deno；本轮验证版本为 Linux x86_64 Deno 2.9.8。Python wheel 不包含 Deno，可从 [Deno 官方发行](https://github.com/denoland/deno/releases/tag/v2.9.8)安装到独立运行目录，再把该目录加入程序或 worker 的 PATH。不要把 Skill 的环境加入网站 PATH。Deno 文件身份与试验结果见[获取记录](../experiments/2026-10-24-youtube-acquisition.md)。

YouTube 元数据及媒体均支持 urllib 的标准 HTTPS 代理变量。国内环境可以向单个进程显式传入已有 HTTP 代理，例如：

```sh
https_proxy=http://127.0.0.1:7890 \
  drum-score 'https://youtu.be/视频ID' --output /absolute/path/new-result
```

将 `视频ID` 替换为实际 11 位 ID，代理地址替换为该运行环境已配置的地址。代理必须允许向已核验的公共数值 IP 建立 CONNECT 隧道，TLS 仍验证原始 YouTube 或 Google 视频域主机名。只接受浏览器页面并不能证明代理支持媒体传输。Windows 本机代理也不自动成为 Linux 服务器的代理。

B站路径仍忽略代理变量。回滚 YouTube 代理设置时，移除为该进程添加的代理变量，并在独立环境中切回原发行。这里没有修改全局配置、部署服务或购买代理，也不从订阅、配置或浏览器中读取凭据。

## 获取与完整性

YouTube 在受监督的独立获取进程中运行。元数据优先使用 `web_embedded` 客户端，解析失败时再尝试一次默认客户端；任何目标域、地址或响应大小安全拒绝不触发回退。客户端尝试共用原转换期限。

yt-dlp 只注册 YouTube 视频 extractor，禁用插件、用户配置、Cookie、netrc、账号参数、缓存和远程组件安装。Deno 使用空白 HOME 与干净环境，执行本地安装的 EJS 组件。元数据响应与 gzip 解压正文分别限制为 8 MiB，原始异常和签名地址不进入公开日志或产物。

解析请求只接受明确的 YouTube API/播放器域与 Google 视频域。媒体只接受 `*.googlevideo.com` 的 HTTPS 地址。YouTube 路径只使用 IPv4，检查该地址族的全部 DNS 回答，拒绝任何非公共地址，连接固定已核验 IP；每次重定向重复域与地址检查，并剔除代理认证头。没有禁用 TLS 校验或放开任意网址。

媒体复用 B站的受限原生视频轨获取与实测校验。优先选择独立视频轨及最高原生分辨率；不为绕过输入额度而静默缩小。只有直接 HTTPS 完整轨可用，纯分段 HLS/SABR 等格式返回 `unsupported_stream`。来源大小受调用方输入额度和 2 GiB 获取上限共同约束，完整曲长、实测分辨率与首帧解码均须通过。YouTube 的整秒时长容差为 1 秒，写入来源记录；B站仍为 0.5 秒。文件保留、取消、进程树清理和发布沿用现有程序契约。

旧 B站规范来源字段不变。YouTube 来源增加 `kind=youtube` 与 `video_id`，不更改 SQLite schema，备份恢复使用同一规范化入口核验两类来源。

## 常见失败

| 错误码 | 含义与处理 |
| --- | --- |
| `dependency_missing` | 安装程序自身固定依赖及 Deno，再检查 worker 的 PATH。 |
| `youtube_challenge` | YouTube 要求机器人或身份验证。稍后重试，或在另一个受控出口验证匿名获取。不会自动导入 Cookie。 |
| `public_api_unavailable` | 匿名解析或出网失败，查看脱敏阶段与异常类型；不要公开原始解析输出。 |
| `unsafe_media_target` | 域、DNS 或重定向不符合公共 HTTPS 约束。检查出网与 DNS，不关闭保护。 |
| `unsupported_stream` | 来源受限或只有不支持的格式，不猜测不可用内容。 |
| `download_too_large` | 最高原生轨超过输入额度，或响应超过边界。 |
| `incomplete_video` | 下载实测时长与整条视频元数据不符。 |

真实下载试验、合成入口验证与真实鼓谱转换是不同证据。当前记录见[获取试验](../experiments/2026-10-24-youtube-acquisition.md)；不要把普通视频下载成功或合成 PDF 当作音乐校对。
