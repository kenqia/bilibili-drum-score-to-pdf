# 四种 B站下载器的隔离实测

2026-10-22，在腾讯云服务器上对同一个公开视频执行有界匿名下载。BBDownNext 2.3.0 和 bilix 0.18.9 直连下载成功，两份文件均通过整段解码。Bili23 1.1.1 和恢复 TLS 证书校验的 lux 0.24.1 在直连、魔戒代理下均遇到 HTTP 412。

建议优先评估 BBDownNext CLI，保留 bilix 作为对照。此次只验证下载能力，没有接入生产网站，也没有开放业务。成功结果限于本次时间、服务器和公开视频，不保证其他视频、清晰度或后续请求都成功。

## 测试条件

目标为[小星星动态鼓谱（简单版）](https://www.bilibili.com/video/BV1np421S78S?p=1)。四个工具使用相同 URL，单任务、受限并发，不进行循环重试。没有提供用户登录凭据，使用新 HOME 和独立输出目录；bilix 显式设置 `browser=None`、`sess_data=None`，不加载浏览器 Cookie。

服务器为 Ubuntu 24.04、Linux x86_64。工具仅放在独立实验目录 `/opt/drum-downloader-comparison-p3pzgre5`，没有安装进生产虚拟环境。每次下载使用临时 systemd 服务，独立动态用户、私有临时目录、只读系统目录、隐藏用户目录、禁止提权，内存上限 512 MiB、CPU 配额 50%、无 swap、64 个任务、总时限 180 秒，单文件上限 64 MiB。

代理测试临时转发服务器 `127.0.0.1:17890` 到电脑 FlClash `127.0.0.1:7890`。测试前检查端口空闲，建立后确认仅回环监听。代理服务设置 `IPAddressDeny=any`、`IPAddressAllow=localhost`；同一公网 socket 在服务外可连、服务内被过滤。随后通过代理实测出口为 `66.90.99.58`，不同于服务器直连地址。用户此前确认 FlClash 为全局模式，B站连接策略为魔戒节点。

BBDownNext 和 bilix 直连已取得视频，因此没有增加它们的代理请求。Bili23 第一次代理尝试的网络隔离前置检查未能确定结果，没有请求 B站；表格采用后续隔离门槛通过的测试。

## 下载结果

耗时只统计工具进程，不含环境准备、代理出口核验和后续解码。

| 工具及版本 | 云服务器直连 | 通过电脑魔戒代理 | 实际文件 |
| --- | --- | --- | --- |
| BBDownNext 2.3.0 | 成功，9.789 秒 | 未测试 | H.264，746×480，63.756 秒，1,357,431 字节，仅视频 |
| bilix 0.18.9 | 成功，5.300 秒 | 未测试 | H.264，746×480，容器 63.901202 秒，1,829,760 字节，含音频 |
| Bili23 1.1.1 | API 412，无视频 | API 412，1.502 秒，无视频 | 无 |
| lux 0.24.1，恢复 TLS 校验 | 412，1.184 秒，无视频 | 412，5.331 秒，无视频 | 无 |

Bili23 的 `/x/web-interface/view` 返回 412 后触发 `JSONDecodeError`。包装脚本退出码为 0，但工具异常和空媒体列表明确表明下载失败。bilix 的公开页面得到 301、200，媒体分段返回 206。BBDownNext 退出码为 0，输出中没有观察到 412；未为它采集完整 HTTP 请求轨迹。

两份成功视频均由另一个无网络、低权限临时服务执行完整 FFmpeg 解码，退出码 0、错误输出 0 字节、解码 1912 帧。文件也已传回本地并校验 SHA256。实际查看 BBDownNext 视频 20 秒处的截图，画面为小星星鼓谱。

| 文件 | SHA256 |
| --- | --- |
| BBDownNext 视频 | `062c556fee5e6796cc4abbcc511d2a2611728b363edea9eabaa254e0989f8d86` |
| bilix 视频 | `542376db5134675dd5e24709083185efb29a6876e02ffb839519a63a70575c64` |

相同输入 BV、BBDownNext 输出中的 CID `1519093384`、bilix 媒体路径中的相同 CID 和实际画面共同支持样本身份。整段文件解码不等于另行核验来源声明的完整曲长，也不等于完成鼓谱转换、逐符号校对或生产来源绑定验收。本轮没有重新生成 PDF。

## 版本与源码差异

- [BBDownNext 2.3.0](https://github.com/KaiHuaDou/BBDownNext/releases) 使用官方 Linux x64 发布文件，SHA256 为 `8e149b6d90a48bd3665b9c7efb5056e443e4a5c6d04313b8c4d21cfc6e70d114`，已对照发布摘要。CLI 参数为目标 URL 加 `--api web -g v --mux none --single-thread --max-retry 0 --work-dir <独立输出目录> -p 1`。未启用不安全 TLS 选项，未提供用户认证；工具可能生成公开匿名设备标识。
- [Bili23 仓库](https://github.com/ScottSloan/Bili23-Downloader-CLI) 当前源码标为 1.2.0，存在 `Config.sessdata` 与嵌套配置定义不一致的问题。本次没有改源码后冒充原版，而是测试 PyPI 正式包 `bili23==1.1.1`，通过其 `parse(url)` 入口调用。结论只适用于实际测试的版本。
- [bilix](https://github.com/HFrost0/bilix) 使用 `bilix==0.18.9`，调用 `DownloaderBilibili.get_video`，质量参数 0、AVC 编码、分段及视频并发 1；仅在测试进程内将请求重试设为 0，关闭日志，只记录响应主机、路径和状态码，不保存签名查询串。独立 Python 环境的 40 个依赖通过 `uv --no-config pip check`。
- [lux 0.24.1](https://github.com/iawia002/lux/releases/tag/v0.24.1) 的 `request/request.go` 默认 `InsecureSkipVerify: true`。原始二进制未参与联网测试。本次从准确标签源码将这一处改为 `false` 后独立编译，测试二进制 SHA256 为 `c2cd6698686b72576d67c1a97eff0657d1061e175817ca8ff6ee8bcd5efaac3e`。使用 `-retry 1 -n 1 -o <独立输出目录> <URL>`。因此这是恢复证书校验后的对照结果，不能写成原版二进制测试结果。

## 对网站的适配结论

BBDownNext 已证明可作为服务器独立 CLI 下载当前样本。其 `serve` 模式提供 REST API、队列和并发设置，但本轮未启动或验收该模式。网站已经有任务队列，后续可优先评估在现有 worker 内调用受限 CLI，避免重复维护第二套任务生命周期。bilix 与 Python 后台接近，可作为第二候选。

正式接入前仍需确认许可证、版本固定、进程取消、输出和磁盘限制，并让候选工具满足现有匿名获取、来源绑定及完整性校验。还需要其他来源视频、服务器完整转换与生产资源额度验证。此次没有修改网站获取代码，下载成功也不会自动解除待开放状态。

## 生产保护与证据

测试前后 nginx、zju-search、原 mihomo 的 PID 和状态一致。两个鼓谱服务仍为 inactive、disabled、MainPID 0。路由表、策略规则及既有代理监听完全一致，临时转发已关闭，17890 无监听。公网入口保持 HTTPS 503，正常 CA 校验结果为 0。

实验运行时和公开样本保留在独立目录，便于复核，没有加入服务自启。服务器实验目录及 `/run/drum-dl-compare-*` 留存文件没有递归清理。未改生产配置、SSH 配置、全局路由或现有 VPN 配置，未读取账号、订阅、Cookie、token 或私密日志。

脱敏证据和实验脚本位于 `/home/kenqia/issue69-context/downloader-comparison-20261022/`。关键文件为 `bbdown-direct-remote.stdout`、`bilix-direct-remote.stdout`、`bili23-direct-remote.stdout`、`bili23-proxy-remote.json`、`lux-direct-remote.stdout`、`lux-proxy-remote.json`、两份 `*-full-decode.json`、`comparison-after.stdout` 和 `invariance.json`。公开下载样本为 `小星星-BBDownNext-匿名直连.mp4`、`小星星-bilix-匿名直连.mp4`，抽帧为 `小星星-BBDownNext-20s.png`。

本次变更仅增加实验文档，未重跑应用单元测试。已执行真实下载、全文件解码、回读哈希、依赖检查、生产状态对照和文档链接检查。生产应用仍为 `ee9a32010a6ff4966d6d5aa6ed09eef8a34f1e3a`。
