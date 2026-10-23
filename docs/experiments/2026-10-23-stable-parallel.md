# 稳定并行与解码期限修复

2026-10-23，用户明确接受并行时更慢，要求服务器稳定且确实可以并行。此前“八路耗时约两倍”不再是验收门槛。目标仍为不同 IP 最多八路、同 IP 一个未完成任务。没有购买资源，也没有切换正式网站或升级生产库。

## 真实并行与失败定位

所有实验都在 `/srv/drum-score-capacity-20261023` 的独立数据根中运行，正式网站继续运行原发行。测试使用同一个公开来源 `https://www.bilibili.com/video/BV1rH4y1R7Rk?p=1`，298.6 秒、852 × 480。临时 unit 以 `drum-score` 用户运行，CPUQuota 150%、MemoryMax 1 GiB、MemoryHigh 896 MiB、SwapMax 0，并降低 CPU/IO 权重和调度优先级。保护条件为首页探针失败、cgroup OOM 或主机 MemAvailable 低于 256 MiB。任务总期限为 1200 秒，保留有限资源上限。

首先完成两路在线匿名获取与转换，两个任务分别用时 114.302 和 117.053 秒，实际运行重叠约 114.65 秒，均生成两页 PDF。两任务 PDF 与全部预览共六个交付文件 hash 匹配。cgroup 内存峰值为 405,512,192 字节，无 high/max/OOM 事件，113 次首页探针均为 200，最慢约 37 毫秒。

测量器最初误把网站已清理的中间采样当作保留文件核验，收尾发生 `KeyError`，原始报告保留。按 `web_delivery` 只核验 PDF 和全部页面后，从实验库中的 complete 状态及持久产物恢复两路证据，没有重跑。两路 worker 的退出码未在错误前保存，最终记录为未知，不以推定的 0 代替证据。原生采样 PTS、time_base 与 hash 元数据保留，但样本文件本身不再保留。

随后在同样资源限制下，将已捕获的原始公开视频冻结回放八路。来源 SHA256 为 `dd9c4c6898215d22089e1c30d6cd648e21b01195376d7f2b82a92656a5fa8078`，不重新下载或转码。八个任务同时处于采样，峰值内存 864,509,952 字节、无 OOM，但在约 65.8 秒内全部返回 `decode_failed`，没有交付产物。

该失败不是内存耗尽。`VideoReader.sample_records` 和 `read_record` 使用 `min(60, 600 - decode_elapsed)`，每次额外的 60 秒期限在 CPU 争用时杀死了仍在正常解码的 FFmpeg。仅把 worker 的总期限扩大到 1200 秒无法解决。部分终止发生在一帧中间，因此错误可能表现为采样帧不完整。

## 修复与本地验证

应用提交 `0ba65cc` 只移除两处额外 60 秒限制，仍使用 `600 - decode_elapsed` 约束累计解码。监督进程仍执行外层总任务期限、进程树清理、RSS 与磁盘预算，来源 hash、原生运动观察、实际 PTS/time_base 和完整发布条件不变。没有新增参数或依赖，独立 Skill 未修改。

新增快速回归将实际终止定时器加速 120 倍，并运行真实合成解码子进程：旧代码约一秒内在采样与尾帧两分支失败，修复后通过。不把这段虚拟时间当作真实 60 秒 CPU 工作。另在 Python、CLI 和 HTTP/worker 三个公开入口实际进入阻塞的合成解码器，以两秒总期限终止并核验进程和暂存清理。原累计耗时耗尽断言保留。

Python 3.12.12 完整程序回归 200 项全部通过，耗时 158.928 秒。离线 CI 合成重放、构建、compileall、diff 检查通过。基础/web 两份独立 wheel 安装在仓库外实际转换，web 另启动 HTTP 与 worker、下载全部页面和 PDF；依赖检查通过。没有把本地安装结果当作目标机音乐校对。

修复 wheel SHA256 为 `ddfdc74a999e4694662e6d92f7f692e61ba14e23b01856f61a4b38a37117fb92`，29 个包文件与源码逐字节一致。目标机解压到独立 `code-decoder-budget`，相对原候选仅 `video_seek.py` 不同，仍使用服务器原有 Python 3.12.3 与依赖，不改动正式发行的文件或环境。

## 修复后八路冻结回放

在同样的 1 GiB/1.5 核限制下，八个任务全部完成，整批 575.119 秒。已记录八个任务同时采样、配准和分页，至少两个 running 状态重叠累计约 574.56 秒。所有结果的来源 hash 与冻结输入一致，八份 PDF 和全部预览共 24 个登记交付文件 hash 核验通过。

cgroup 内存峰值 886,075,392 字节，约 845.0 MiB；high/max/oom/oom_kill 事件均为 0。主机可用内存最少 642,356 KiB，约 627.3 MiB，没有触发保护停止。进程/线程限制另明确为 TasksMax 256、LimitNOFILE 1024。该回放只证明真实媒体的并行转换，没有把它当作八路在线获取。

## 修复后八路在线获取与转换

最后一轮直接运行八个不同 IP 身份的在线任务，分别执行匿名获取和完整转换，没有使用冻结回放替身。每次获取仍调用原匿名下载实现，仅额外捕获首份公开视频留证。八个任务全部完成，整批 565.468 秒，各任务处理时间为 558.691～564.283 秒。已记录八个任务同时采样、配准和分页，确认实际并行。

全部八份 PDF、十六页预览共 24 个登记交付文件 hash 核验通过，来源 hash 均与前述输入一致。冻结回放与本轮在线转换共十六份结果的 program source hash 均绑定修复后的 `8d38a05379edc27b6a2ac85c7094be59c7d078cb66d5d35bf4f098bc331ceb58`，没有把旧程序结果混入修复验证。未重新看图或音乐逐符号校对，`reliable=false`。

本轮 cgroup 内存峰值 862920704 字节，约 822.9 MiB，high/max/oom/oom_kill 均为 0。主机可用内存最低 635168 KiB，约 620.3 MiB，没有触发 256 MiB 保护。500 次本机正式首页探针均为 200，最大 0.0876 秒。运行中捕获的 cgroup `pids.peak` 为 156，因此旧正式 unit 的 TasksMax 64 不能直接用于八路，候选明确使用 256。

所有临时 cgroup 最终均已消失，仅重置本轮失败测量 unit 的管理状态，失败文件与日志保留。正式 web/worker/nginx/zju-search 均 active，公网 HTTPS 首页为 200，约 53 毫秒。正式发行仍为 `7fa75ac9a8aeaaa3cdea8b2ab9a58e0018235e2c`、schema 仍为 v1；正式 worker 仍为 512 MiB/100% CPU/TasksMax 64，没有自动切换。最终 MemAvailable 1371 MiB，根盘可用 11,609,550,848 字节，使用率 77%；OpenClaw 数据根未重建，共享工具保留。

这些结果支持在现有服务器上尝试有资源保护的八路配置，无需为了此前的速度倍率立即扩容。它们来自同一个 480p、约五分钟的来源，不代表任意八个高分辨率或更复杂视频都能完成。共享 worker 的硬限额继续保护其他服务，超限任务仍可能失败，不取消有限等待、总期限和完整性要求。

## 证据与上线边界

本轮证据根为 `work/engineering/2026-10-23-server-cleanup/`：

- `real-parallel-report.json` 与修正前副本记录两路在线成功、采样文件核验器问题以及修复前八路受控失败。
- `decode-budget-red.log`、`decode-budget-green.log` 和 `decode-deadline-contract.log` 记录失败反馈与专项验证。
- `regression-decoder-budget.log` 记录 200 项回归；`wheel-decoder-budget.json`、`ci-replay-decoder-budget/` 和独立安装日志绑定最终包。
- `real-parallel-fixed-report.json` 记录修复后的八路冻结回放；`real-parallel-live8-report.json` 记录八路在线成功；`live8-checkpoint.json` 保存线程峰值，`stable-parallel-final-state.json` 绑定实际代码和最终服务状态。原始失败记录与旧代码目录保留。

独立审阅确认解码预算仍受累计与总期限约束，并指出撤销 drop-in 后必须先 `systemctl daemon-reload` 再启动服务。候选清单已修正该步骤。静态 unit 核验通过，不代表生产已经切换。明确的资源、数据根、维护与回滚方案见[并行切换候选](../script-product/parallel-rollout.md)。
