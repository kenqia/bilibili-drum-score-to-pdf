# 匿名视频获取维护说明

入口固定 `yt-dlp==2026.8.19`，使用内置 Bilibili extractor 的匿名格式枚举。Python API 不解析 CLI 配置文件，构造器关闭插件加载，参数禁用 Cookie 文件、浏览器 Cookie、netrc、用户名、密码和缓存。不会读取已有登录态。extractor 的 WBI 与 `try_look=1` 路径只用于公开匿名请求，不能保证取得会员画质。

保留 HTTPS BV 和单个正整数 `p` 校验。始终传规范化的显式分 P 链接，拒绝 playlist 或无法匹配所选分 P 的返回。选择原生分辨率最高的 video-only，依次比较帧率、H.264 兼容性和码率。无独立视频轨时才使用含音频的单文件，`single_file_fallback` 明确记录。独立音轨不下载，不混流。多片段旧流暂不支持。

yt-dlp 的当前 Bilibili extractor 未输出 DASH 官方备用地址。项目只在其 `extract_formats` 边界保留官方响应同一视频轨的 `backupUrl`/`backup_url`，同时将无音轨的 DASH 流标为 video-only。媒体候选最多尝试 3 个，每个最多使用 2 个官方备用地址。`format_attempts` 和 `backup_used` 记录是否用了兜底。

所有 extractor 请求通过受限 urllib transport。初始请求和每跳重定向必须是 HTTPS、无 URL 凭据、默认端口；媒体初始地址还须属于 bilivideo.com 或 bilivideo.cn。解析出的所有 IP 都必须公开，拒绝回环、私有、链路本地及其他非公开地址。实际连接固定解析结果中的数值 IP，TLS 仍校验原域名，避免校验后再次 DNS 解析。重定向最多 5 跳。

传输遵循环境 HTTP CONNECT 代理配置。代理是用户指定的传输端点，可以位于本机；隧道目标使用已验证的公开 IP，避免把源站 DNS 验证委托给代理。源站请求不携带 Cookie、Authorization 或 Proxy-Authorization。代理凭据不写记录，HTTPS 和 SOCKS 代理未专项验证。

连接超时 20 秒，extractor 响应最多 2 MiB，视频最多 2 GiB。独立工作进程总时限 30 分钟，覆盖 DNS、接口、下载及 ffprobe/ffmpeg；探测和首帧解码各最多 30 秒。获取进程组在可捕获的失败或中断后停止。后续谱面转换时限另计。

下载在系统独立 staging 内完成，签名 URL 只在工作进程内存中存在。ffprobe 记录实际宽高、编码与帧率，ffmpeg 验证首帧可解码。实测尺寸小于格式标记时返回 `media_resolution_mismatch`，不会静默把伪高清输入发布为成功。发布先复制到目标文件系统，再用独占硬链接提交源文件，避免跨文件系统直接 rename。强杀时的发布残留与同目录恢复规则由获取生命周期任务继续完善。

只向 CLI 返回固定脱敏原因、HTTP 状态码和安全元数据，不显示第三方异常、服务器自由文本或请求头。获取失败提示清晰本地视频兜底；接口变化、412、格式不支持和解码失败均不能当作本地谱面算法故障。

2026-10-06 使用隔离 uv 环境验证后端版本 2026.08.19。离线统一 CLI 测试使用受控 yt-dlp/HTTP/socket 边界及真实编码 fixture，不能证明 B站现场可用。本轮没有访问真实 B站媒体，也没有验收高清整曲。实时 smoke check 必须另记录日期、BV、分 P、匿名状态、选中格式与实测参数，不保存媒体地址或原始 API 响应。
