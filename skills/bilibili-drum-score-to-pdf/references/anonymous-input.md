# 匿名视频获取维护说明

普通 BV 链接先请求 `https://api.bilibili.com/x/web-interface/view`，按所选分 P 取得 CID，再请求 `https://api.bilibili.com/x/player/playurl`，参数为 `bvid`、`cid`、`qn=80`、`fnval=1`、`fnver=0`。没有 Cookie、认证、签名密钥、session、try_look 或 high_quality 参数。播放请求返回的质量可能低于 `qn`；下载后以 ffprobe 实际宽高为准。

[社区视频流接口文档](https://github.com/bilibili-plugins/bilibili-api-collect/blob/master/docs/video/videostream_url.md)将旧 playurl 接口标为旧路径，当前新的 WBI 路径要求签名。这份文档不是 B站官方稳定性承诺。旧路径曾在 2026-10-06 对 BV1b5411x7Ku 成功返回匿名 quality=16、实际 640×360，而视频元数据为 1920×1080。这个低清结果不能用于高清打印验收。

仅处理单个 MP4 地址，允许 HTTPS 且主机为 bilivideo.com、bilivideo.cn 或它们的点分子域。公开 API 地址固定，不使用用户指定主机。禁用自动代理、Cookie 和重定向，拒绝非 HTTPS、userinfo、额外端口和其他媒体主机。下载地址留在内存中，失败消息不输出异常原文或服务器自由文本，源视频文件名只含 BV 和分 P。

[Python urllib.request](https://docs.python.org/3/library/urllib.request.html)提供 opener、socket timeout 与自定义重定向处理。timeout 限制阻塞传输操作，不保证包含 DNS 或多 IP 连接尝试的总墙钟时长。当前 WSL 用 `timeout 120s` 包裹链接命令；外部终止时可能尚无 manifest，按网络获取失败转本地视频。[urllib.parse](https://docs.python.org/3/library/urllib.parse.html)负责拆解 URL，安全检查由调用方显式完成。

任何网络异常、HTTP 拒绝、非零 API code、无效 JSON、分 P 不存在、无单文件 MP4、未知媒体域、重定向、响应超过上限或画质不足都会停止。不给这些失败加自动重试，不迁移到需要认证的新接口。向用户报告原因和实际尺寸，使用用户提供的清晰本地视频继续原来的谱面还原意图。

离线链接测试替换 urllib 公开传输响应，下载真实编码夹具并调用统一 CLI。它们验证转换集成，不证明外部服务可用。实时 smoke check 必须另记录日期、BV、分 P、quality、实测宽高及处理结果，不保存原始 API 响应或媒体地址。
