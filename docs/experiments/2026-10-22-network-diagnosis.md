# B站匿名请求与代理检查

2026-10-22，按用户要求依次检查静默后重试、程序请求方式、现有代理链路和 Windows 本机公开页面。业务继续保持待开放，未启动服务器鼓谱服务，未修改生产程序、unit 或代理配置。

## 结果

| 检查 | 实际观测 | 可以得出的结论 |
| --- | --- | --- |
| 静默后单次重试 | 上轮最后探测结果写于 11:26:40，本轮 11:43:52 CST 单次直连 GET 同一公开页面，145ms 返回 HTTP 412 | 至少约17分钟的静默未解除此次拒绝；不能据此断言永久封禁 |
| 程序请求 | HTTPS GET、yt-dlp 默认浏览器 User-Agent、TLS 主机名与证书校验、显式公共地址约束；针对性离线测试22项通过 | 未发现基本 URL、请求头丢失或 CONNECT/TLS 实现错误；测试不能证明第三方风控接受脚本 |
| 显式代理 | 实际 TCP 连接 127.0.0.1:7890，成功建立 CONNECT；随后 B站仍返回412 | 该诊断请求确实进入现有代理，不能把结果描述成“代理根本没连接” |
| 代理公网出口 | 两条路线访问 api.ipify.org 失败；4.ipw.cn DNS 解析失败；直接访问1.1.1.1的中立检测分别超时和 TLS EOF | 没有取得可比较的出口 IP，不能确认代理是否更换公网出口，更不能确认 B站分流使用了其他出口 |
| Windows 原生 curl 直连 | 禁用 curl 配置与代理，不加载 Cookie；TLS 阶段失败，curl exit35、HTTP状态000 | 该客户端没有完成 HTTP 请求，不能解释为 B站返回412 |
| WSL 同程序传输层直连 | HTTP200，58265字节，但没有目标BV号或 `window.__INITIAL_STATE__` | 仅200不能证明目标视频页面可用；本次未保存正文，不能进一步确定页面类型 |
| Windows 原生 Edge | 全新隔离目录、禁用代理、不复用登录态，单次导航正常显示标题“小星星动态鼓谱（简单版）_哔哩哔哩_bilibili”，包含正确BV号与初始元数据 | 公开页面本身可在本机正常浏览器访问，截图已实际查看，谱面画面可见；未验收完整视频播放或下载 |

本机浏览器与脚本也出现差异，因此还不能认定“只有云服务器 IP 受限”。现有证据支持云端匿名脚本请求持续被拒绝，浏览器与脚本的 TLS/客户端行为、匿名状态或其他风控条件也可能参与。以上是诊断假设，尚无可以唯一定位到 IP、请求频率或具体风控规则的证据。

## 请求实现核对

`anonymous_backend.py` 复用固定版 yt-dlp 2026.08.19 的 Bilibili 提取器。主路径先读取网页，后续播放信息使用其签名流程；本产品的公开 API 回退另核验 BV、分P、权限与完整时长。固定版本的[上游源码](https://github.com/yt-dlp/yt-dlp/blob/2026.08.19/yt_dlp/extractor/bilibili.py)可用于核对调用路径，不能保证上游接口长期兼容。

`PublicTransport` 使用 urllib 的环境代理发现，显式 direct 路线关闭环境代理，遵循 [Python 3.12 ProxyHandler 文档](https://docs.python.org/3.12/library/urllib.request.html#urllib.request.ProxyHandler)。当前生产 worker unit 没有显式代理变量，主路径是否使用环境代理和回退强制直连也须区分。上轮给独立诊断进程指定代理，不等于已经配置生产 worker 代理。本轮没有读取系统全局环境、代理规则或认证材料，不能对这些未知配置作额外断言。

代理 CONNECT 使用核验后的数字公共 IP，TLS 保持源域名。这保留了 DNS 固定与主机名校验，但只凭 CONNECT 成功不能知道代理后续按何种规则分流。确认公网出口或修改代理规则需要另有证据，不能靠同为412来推断。

本轮运行如下离线测试，22项、5.128秒全部通过，无跳过。

```sh
PATH=/home/kenqia/issue69-offline-release-venv/bin:$PATH \
  /home/kenqia/issue69-offline-release-venv/bin/python \
  -m unittest discover -s tests -p test_link_input.py -v
```

覆盖默认请求头、实际 CONNECT 数字目标与 Host、TLS SNI、IPv6失败后IPv4重试、凭据隔离、响应上限、重定向与拒绝后的清理。未改代码，不重复全量150项，也未触发新的真实转换任务。

## 证据与当前边界

脱敏脚本、JSON、测试结束输出和已查看的 Windows 截图位于 `/home/kenqia/issue69-context/network-diagnosis-20261022/`，关键文件为 `cooldown-retest.json`、`proxy-proof.json`、`egress-fallback.json`、`egress-literal-ip.json`、`desktop-compare.json`、`windows-browser.json`、`windows-browser.png` 和 `request-tests.log`。测试日志保留结束输出，最初两项的通过信息在工具回执中。

Windows Edge 使用新建的专用临时 profile，进程正常退出；没有连接用户日常浏览器，没有读取 Cookie、localStorage、认证、代理配置或私密日志。检测正文仅在内存中计算有限标记，未保存 HTML 或签名媒体 URL。

不再继续轮换检测端点或频繁请求 B站。公网仍为 HTTPS503，鼓谱两个服务保持停止和禁用自启，原部署和备份不变。恢复部署业务前仍须获得可用匿名获取路径并完成目标机完整转换验收，见[部署状态](2026-10-22-server-deployment.md)。
