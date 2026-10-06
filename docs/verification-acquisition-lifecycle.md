# 获取生命周期与同目录重试验证

2026-10-07，#14 基于集成提交 `80d701a` 实施，沿用已确认的统一 CLI 边界。没有修改认证、全局配置或访问真实 B站媒体。依赖沿用项目 requirements，由 uv 隔离环境运行。

第一项红测复现获取失败后写出的 manifest 阻止同目录重试；结果缺少 acquisition 阶段标记。新增严格的 acquisition-only 诊断识别后，同目录再次获取成功，并保护已有 PDF。真实 CLI SIGTERM 红测随后得到退出码 -15，未返回 JSON，并遗留仍在下载的工作进程；该红测遗留的已知进程组已停止。修复后返回 `acquisition_interrupted`，清理本次 staging，目录只含可重试诊断。最初缺少 yt-dlp 的执行和 launcher 参数错误均不计为红测。

获取使用一个单调时钟 deadline。它涵盖 DNS、extractor、连接、所有格式与备用地址尝试、下载、ffprobe/ffmpeg、目标文件系统复制/fsync 和工作进程退出。主进程等到工作进程正常退出，才独占发布完整源视频。复制目标位于结果目录外，因此复制中超时或强杀没有最终目录 partial。可捕获中断清理两个本次 staging；Linux parent-death signal 在 CLI 强杀后停止获取进程组。强杀可能留下目录外 staging，不能自动删除未知残留；非 Linux 强杀行为没有验证。

验证命令均在仓库根目录执行：

```sh
uv run --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt python -m unittest discover -s tests -p test_acquisition_lifecycle.py -v
uv run --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt python -m unittest discover -s tests -p test_link_input.py -v
uv run --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt python -m unittest discover -s tests -p test_link_input.py -k probe_failure
```

生命周期 6 项通过，最终复跑耗时 15.325 秒。真实 CLI 进程覆盖 DNS、extractor、连接、下载停滞，探测子进程停滞，工作进程因后台子进程等待退出，目标复制停滞，SIGTERM 与 SIGKILL。每次通过 stdout JSON、最终目录和 OS 进程状态判断结果，不调用获取私有函数。网络、第三方 extractor 和受阻文件复制使用边界替身；ffprobe/ffmpeg、进程组与信号均实际执行。不存在仍在运行的本轮 launcher 或探测进程。被强杀的孤儿子进程可能短暂处于 zombie 状态，等待系统 reaper 回收。

匿名输入回归 19 项通过，66.283 秒，包括正常 video-only、备用地址、代理、DNS 固定、签名脱敏、现有结果保护，以及 /tmp 下载 staging 到 /dev/shm 结果的真实跨文件系统发布。随后新增探测失败后的同目录重试通过，7.916 秒。现有匿名测试现在共 20 项；上述结果为 19 项回归加 1 项专项，未声称新一轮 20 项整套结果。

这些是受控 CLI 验证，不能证明 B站在线可用、匿名高清或《七里香》整曲通过。获取时限也不是整次转换时限：本地探测最多 30 秒，采样解码最多 600 秒，末帧解码最多 60 秒；谱面分析与 PDF 排版没有统一 deadline。README 与 skill 已同步说明。
