# 正式八路并行切换

2026-10-23，用户明确批准[上线和回滚清单](../script-product/parallel-rollout.md)后，在现有腾讯云双核、2 GB 服务器完成切换。正式网站启用最多八个不同 IP 的转换，同 IP 仍最多一个未完成任务；超过执行名额的任务排队。没有购买扩容、修改 nginx/TLS/DNS 或改动独立 Skill。

八路真实在线转换已在上线前独立环境完成 8/8；本轮在最终生产 unit 和恢复后的数据库上重新验证两路真实 HTTP 任务。两类证据分别保留，不把配置的八路上限当作本轮又执行八路。前一轮的输入规模、耗时和内存边界见[稳定并行实验](2026-10-23-stable-parallel.md)。

## 安装与数据恢复

新发行位于 `/srv/drum-score/releases/parallel-ddfdc74a999e4694`。wheel SHA256 为 `ddfdc74a999e4694662e6d92f7f692e61ba14e23b01856f61a4b38a37117fb92`，29 个包文件核验一致；公开 BBDownNext 二进制 hash 与实测固定版本一致，公开许可证和构建材料保留。版本号仍为 `0.1.1`，发行身份由包 hash 区分。

新环境使用原发行 wheelhouse 和版本约束离线安装，不修改旧环境或系统 Python。系统缺少 ensurepip，首次创建普通 venv 失败，尚未停止正式服务；随后使用 `venv --without-pip` 和旧 pip 的 `--python` 安装到新环境。依赖检查通过，安装过程与失败日志保留。

维护前核对正式服务均 active、没有未完成任务，磁盘可用约 10.8 GiB。停止 web 入口并排空 worker 后，用旧发行备份并核验 v1 快照：

`/var/backups/drum-score/backup-before-parallel-20261023-122229`

新维护入口 `upgrade-v1` 从该快照恢复到原先不存在的 `/var/lib/drum-score-restore/parallel-v2-20261023`。schema v2 核验通过，旧库 44 条 complete 记录的原完成时间和到期时间保持一致，恢复副本重新登记文件身份。原库 `/var/lib/drum-score` 和旧发行 `7fa75ac9a8aeaaa3cdea8b2ab9a58e0018235e2c` 保留，没有用新 worker 打开原库。

## 私有验收与开放入口

安装两份 `90-parallel-budget.conf`，原 unit 保留。worker 使用八路、共享 MemoryMax 1 GiB、MemoryHigh 896 MiB、SwapMax 0、CPUQuota 150%、TasksMax 256、LimitNOFILE 1024；单任务总期限 1200 秒，累计解码预算仍为 600 秒。完整参数见上线清单。

原子切换 current 后，先用临时 profile 让正式 web 监听本机 8792。验收直接通过 HTTP 提交，不替换匿名获取或转换实现，使用与八路测试相同的五分钟 480p 公开来源。不同 loopback 源地址模拟两个不同 IP；新建实验任务的访问能力只留在进程内，不写入报告。

验收结果：

| 检查 | 结果 |
| --- | --- |
| 两个真实在线任务 | 2/2 complete，整轮约 118.770 秒 |
| 实际运行重叠 | 114.990 秒，记录两任务同时采样、配准 |
| 下载完整性 | 两份 PDF、四页预览，共六文件 hash 匹配 |
| 同 IP 重复提交 | 返回 HTTP 429 |
| 另一个任务取消 | HTTP 请求成功，最终 cancelled |
| worker 内存峰值 | 371572736 字节，约 354.4 MiB |
| 内存事件 | high/max/oom/oom_kill 全为 0 |
| 主机可用内存最低 | 1190960 KiB，约 1.14 GiB |
| 其他服务 | nginx、zju-search 保持 active |

验收后仅按记录的身份/hash 删除临时 `99-parallel-verify-port.conf`，执行 daemon-reload，核对有效启动命令使用新根与 8791，再重启 web。北京时间约 20:24:35 开放正式入口，20:24:46 完成十次公网 HTTPS 探针，全部为 200，最慢 0.0611 秒。维护从 20:22:29 开始，约两分多钟；该区间入口不可用，不计为普通请求可用率。

本轮没有重新看图或逐符号音乐校对，complete 仍仅表示完整产物发布，`reliable=false`。任意八个复杂高分辨率输入的成功率没有得到保证；资源超限仍可能使任务受控失败，共享硬限额继续保护主机。

## 保留材料与后续操作

本地证据目录为 `work/engineering/2026-10-23-parallel-deploy/`，包含 `prepare.py`、首次安装失败及成功记录、`deploy.py`、`deployment.json`、`final-check.py` 和 `final-state.json`。服务器新发行下的 `installation.json` 与 `deployment.json` 记录包身份、快照路径、逐步时间和新增 profile 身份/hash，不含访问能力或真实认证值。

收尾额外监测约 40 秒，二十次公网 HTTPS 请求全部成功，最大 0.0523 秒；本地 WSL 独立请求也返回 200。最终 web/worker 均 active、无自动重启，临时 8792 覆盖已撤销，正式有效参数与 profile hash 核验通过。库内为 46 条 complete、1 条 cancelled、22 条 expired，没有未完成任务。磁盘可用 11115663360 字节，约 10.35 GiB，主机可用内存约 1.33 GiB。

本轮未触发回滚。旧发行、旧数据根、v1 快照与新增配置的精确撤销材料保留。公开新入口后如需回滚，先停止接收新任务并保留新数据根，处理新任务的恢复或交付，不能直接返回旧库而丢弃新任务。OpenClaw 的清理与其数据不可恢复边界见[清理记录](2026-10-23-server-cleanup.md)。
