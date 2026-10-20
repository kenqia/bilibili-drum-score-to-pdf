# 运行边界与安装核对

本 Skill 自包含 `SKILL.md`、`scripts/` 和 `references/`。从 SKILL.md 的实际位置定位根目录，在宿主可发现的目录安装整个 Skill 文件夹。读取 SKILL.md 不等于宿主已经完成持久安装。显式选择本 Skill 后提供链接即可启动默认 PDF 流程。

安装后确认宿主技能列表或选择器可以找到本 Skill，脚本及本文档同目录的阶段协议可读，并运行 `scripts/convert.py --help`。宿主必须能读写文件、运行 Python 脚本、实际查看原生图片和 PDF 页面；Python 3.12、uv、ffmpeg、ffprobe、Poppler 是独立环境依赖。

公开获取只接受规范 HTTPS B站 BV URL 及合法分 P。匿名获取不加载用户配置、Cookie、netrc、插件或模型认证。保留公共 DNS/TLS 校验、协议和重定向限制；签名媒体地址和后端原始异常不写入公开日志。不能为了完成任务绕过这些保护。

匿名获取默认沿用环境代理。遇到代理 CONNECT 403 或视频网页 HTTP 412 时，程序在原下载总期限内尝试一次公开 API 直连恢复，不修改宿主代理配置或环境变量。恢复复用固定版本 yt-dlp 的 WBI 和格式提取，核对 BV、分 P、试看标记、API 时长及文件实测时长；受限、互动、跳转或不完整来源停止。公共地址固定、TLS、媒体域名、重定向、大小限制和不覆盖保护继续生效。恢复结果记录 `acquisition_route=public_api_direct` 与脱敏 `fallback_trigger`。代理 407、来源 HTTP 403、私有地址和普通网络错误不触发此恢复；宿主不允许直连或恢复仍失败时报告实际诊断，不读取 Cookie 或让 Agent 自行改代理。

获取、重试、探测共享资源期限。原生解码累计最多600秒、单次最多60秒，下载总期限默认1800秒。取消和失败必须清理临时解码资源，独占发布完整文件，不覆盖已有产物。原视频与派生产物分开保留，来源和材料通过实际 PTS、time_base 和 hash 绑定；引用损坏时停止并报告。

恢复和布局调整读取 `stage-recovery-layout.md`。来源疑点未解决时保持 blocked；轮廓转描不是音乐识别，也无法补出隐藏记号。后续同内容重复音乐保留，同一原谱位置的重复截图去重。最终每页实际审阅绑定当前独立 output_revision，程序检查不能冒充音乐校对或真实看图。未知宿主调用成本为 null。

当前支持已有白底多行、固定比例、向上推进或可确认有序翻页的谱面。真实整曲验收来自 Codex 的指定样本，不能推广为所有视频或宿主的准确率。没有谱面的演奏视频不支持音频扒谱。

## Windows 原生环境

含空格或中文的路径使用引号；PowerShell 文件操作使用 `-LiteralPath`。JSON 请求可由 Python 以 UTF-8 写入，入口也接受 UTF-8 BOM。若 NumPy/OpenBLAS 报线程资源分配错误，仅在当前进程环境将 `OMP_NUM_THREADS`、`OPENBLAS_NUM_THREADS`、`MKL_NUM_THREADS` 设为 `1` 后重试，不修改全局配置。

需要检查依赖或宿主发现时运行 `scripts/host_check.py`；显式 `--probe-decode` 提供有限时、无网络的合成解码检查。依赖就绪不代表生图或图片查看能力可用。
