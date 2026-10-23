# 网站并行与服务器清理方案

本文记录 2026-10-23 的容量讨论。需求共识已确认，本地改造与隔离验证已获授权；服务器清理、配置修改、生产压测和部署仍需在具体清单与回滚方案准备好后确认执行。

## 已确认的目标

- 第一阶段支持 8 个不同 IP 的转换任务同时执行。单 IP 继续最多一个未完成任务，超出全站执行名额后排队。
- 优先减少转换排队。单任务速度目前可以接受，提速作为次要优化，保留谱面完整性与现有安全约束。
- OpenClaw 已不再使用，准备完整卸载方案。执行前明确具体服务、安装目录、删除范围和回滚方式。
- 允许提出服务器扩容建议。先提供测量结果与推荐配置，再由用户决定购买。
- 扩容预算优先，需要给出低成本方案及其速度代价，不以 8 核 16 GB 作为默认购买配置。
- 八路满载时，单任务处理时间目标不超过相同视频独占运行时的约两倍。比较不包含排队时间；等待时间单独记录。该目标尚未经过验证。
- 独立 Skill 不在本次改造范围内。
- 接受一次短暂维护：停止接收新任务，等待现有转换完成后切换，保留未到期结果和原期限。具体服务器操作清单与回滚方案准备好后另行确认执行。

## 当前事实

代码基线为 `2fc366aa16fd44ad8594a5b4ad309a01e0f77b55`。2026-10-23 17:09 +0800 通过既有 SSH 连接进行只读盘点，未读取认证、进程参数、环境变量、任务来源或原始日志。

| 项目 | 实测状态 |
| --- | --- |
| CPU | 2 核，负载均值 0.18 / 0.41 / 0.36 |
| 内存 | 总计 1967 MiB，可用 807 MiB |
| Swap | 已用 464 MiB，总计 10179 MiB |
| 根磁盘 | 总计 50G，已用 41G，剩余 6.9G，使用率 86% |
| 网站 web | active/enabled，内存约 37 MiB，上限 128 MiB，CPUQuota 50% |
| 网站 worker | active/enabled，内存约 72 MiB，上限 512 MiB，CPUQuota 100% |
| OpenClaw gateway | root 用户服务 active/enabled，RSS 约 371 MiB，cgroup 内存约 384 MiB |
| `/root/.openclaw` | 4.1G，仅统计大小，未读取内容 |
| `/root/.nvm` | 1.6G，尚未确认共享依赖，不列为整体删除对象 |
| `/srv/drum-score` | 1.5G |
| `/var/lib/drum-score` | 67M |
| `/var/backups/drum-score` | 59M |
| `/var/log` | 1.7G，未读取内容，不列为整体删除对象 |
| `/var/cache` | 152M |

以上是瞬时盘点，不是负载测试。OpenClaw 目录大小与进程 RSS 不等于最终可释放空间和可用内存。

## 并行改造的约束

当前全站串行由三个机制共同实现：`schema.py` 的 `single_active` 唯一索引、`jobs.py` 的活动任务检查、`worker.py` 的全局排他锁与同步执行。只扩容服务器或增加 worker 进程不会解除这些约束。

实施设计必须同时覆盖以下事项：

- 每个 attempt 独立执行、取消和清理，一个任务不能终止其他任务的进程或删除其目录。
- 恢复不能把其他仍在运行的任务当作遗留任务处理。
- 原子预留所有活动任务的临时空间。当前单次 1 GiB 临时预算与 2 GiB 总目录额度不能直接用于八路并行。
- 保留 `finishing` 完成决定、原到期时间、未知文件和文件身份保护。
- schema 版本升级、停服备份屏障与代码回滚使用匹配的恢复方案。
- 维持匿名获取、公共地址/TLS 校验、全部页面交付及 `reliable=false`。

## 测量与验收

本地已完成八路离线合成实验，所有任务完成，但八路最慢处理耗时仍超过独占中位数的两倍。实验包含阶段耗时，未使用真实 B站传输，也未在目标云服务器施加硬内存限制。方法、CPU 拓扑、数值和失败过程见[并行容量实验](../experiments/2026-10-23-parallel-capacity.md)。

后续先选代表性短、中、长视频建立单任务基线，再验证 2、4、8 路转换。记录等待时长、实际处理时长、完成率、CPU、cgroup 内存峰值、磁盘峰值与网络速率。生产负载测试需要单独明确执行范围。

回归复用 `tests/test_web_worker.py`、`tests/test_product_lifecycle.py`、`tests/test_maintenance.py` 和 `tests/test_public_contracts.py`。迁移原有串行断言并增加并行隔离证据，不直接删除仍适用的断言。程序全回归入口见 [验证指南](../verification.md)，真实来源和全部预览验收另行记录。

## 预算优先的配置比较

用户提供当前实例为腾讯云轻量应用服务器 Lighthouse，新客专享型，上海五区，2 核 2 GB、50 GB SSD、4 Mbps、300 GB/月。以下月价来自 2026-10-23 用户提供的控制台套餐文字。差额按同规格展示价 48 元/月计算，不代表当前实际账单或剩余期限的升级补差。

| 候选 | 展示月价与相对 48 元的差额 | 约束与建议 |
| --- | --- | --- |
| 现有 2 核 2 GB、50 GB、4 Mbps | 48 元，差额 0 | 八个任务的单任务 512 MiB 上限合计 4 GiB，尚未计系统与其他站点，不作为八路生产目标 |
| 2 核 4 GB、60 GB、5 Mbps | 65 元，差额 +17 元/月 | 最便宜的内存缓解方案，CPU 不增加。只能作为另行同意减少并发的过渡方案，不能满足已确认目标的容量承诺 |
| 4 核 8 GB、120 GB、10 Mbps | 210 元，差额 +162 元/月 | 列表中最低价的四核候选，优先评估。八路共享 CPU，约两倍目标尚未成立 |
| 4 核 16 GB、180 GB、12 Mbps | 305 元，差额 +257 元/月 | 比 210 元多 95 元，CPU 不增加。没有实测内存瓶颈前不推荐 |
| 8 核 16 GB、270 GB、18 Mbps | 500 元，差额 +452 元/月 | 列表中最低价的八核候选，成本明显增加。尚未验证云上八路目标，不建议现在直接购买 |

另一组 4 核 8 GB 为 230 元/月，主要增加磁盘和带宽，优先比较 210 元档。低价 2 核 8 GB 套餐同样不能缓解 CPU 争用。现有 4 Mbps 出站带宽理论合计约 0.5 MB/s，预览和 PDF 同时下载会共享带宽；不能据此认定 B站入站获取也限制为 4 Mbps。

可用 CPU 秒解释速度代价：假设每个任务有 C 秒的单核计算工作，八个同类任务总计需要 8C 核秒。四核全部可用时，这部分工作的整批完成时间理想下界为 2C；两核为 4C，八核为 C。当前 worker 的 CPU 上限为一核。上述模型不包含其他服务抢占、线程效率、下载等待或磁盘争用，不能当作端到端耗时预测。

建议先完成获准的清理与独立目标机测量，再决定是否购买 210 元档或其他资源。若允许降低第一阶段同时执行数，65 元档可以单独评估两路；这会改变已确认的八路需求，不能擅自采用。八路约两倍目标保留，达到前不报告验收完成。磁盘需求根据清理后水位、八路暂存预留、有效结果和备份计算。

## 本地实现

已采用单机唯一调度器，配置 `--concurrency 1..8`，默认一路。监督线程分别调用现有独立转换进程，显式绑定自己的任务上下文和 guardian 租约。所有任务停止后才释放全局维护锁，完成任务仅恢复自己的暂存目录。依据和版本代价见 [ADR 0008](../adr/0008-bounded-conversion-scheduler.md)。

schema v2 移除旧单活动索引；显式 `upgrade-v1` 从完整旧快照恢复到新目录后升级，不自动修改线上旧库。容量检查在领取事务内为全部活动任务及新任务预留完整临时额度，同时计算已落盘数据，采用保守预算。阶段耗时已写入结果资源摘要；完全相同且无原生运动歧义的帧复用零位移验证，保留歧义拒绝。

任务名额按提交顺序分配，保留每 IP 一个未完成任务。资源不足时维持等待或拒绝新提交，不能挤占其他任务的预留，也不能提前删除有效结果。单任务失败不得停止其他任务；服务重启后未作完成决定的任务保持中断，由用户显式重试。

## 尚待决定

- 扩容购买决定、实际升级补差及目标机测量范围。
- OpenClaw 在目标机的可恢复备份核验与永久删除批准。
- 真实视频和目标机硬资源验收，以及最终 unit 参数。

程序、本地测试与文档已修改；部署文件和服务器保持原样。本地合成测试不代表八路生产容量或音乐校对通过，最新证据见[验证指南](../verification.md)。

## OpenClaw 清理清单与回滚

已确认 root 用户的 `openclaw-gateway.service` 为 active/enabled，系统 `openclaw-upgrade-guard.service` 为 inactive/enabled。以下是待批准清单，不是已执行记录：

| 对象 | 精确路径 |
| --- | --- |
| 用户 unit 与历史副本 | `/root/.config/systemd/user/openclaw-gateway.service`、同路径 `.bak` |
| 用户启用链接 | `/root/.config/systemd/user/default.target.wants/openclaw-gateway.service` |
| 系统 guard unit 与启用链接 | `/etc/systemd/system/openclaw-upgrade-guard.service`、`/etc/systemd/system/multi-user.target.wants/openclaw-upgrade-guard.service` |
| 数据和工作目录 | `/root/.openclaw`，gateway 工作目录为其下 `workspace` |
| Node 环境中的 CLI 入口 | `/root/.nvm/versions/node/v22.22.1/bin/openclaw` |
| 入口转交目标 | `/root/.local/share/pnpm/openclaw` |

执行前再次核对路径身份、unit 状态和共享依赖。先明确禁用并停止 gateway 和 guard，确认进程退出与其他网站正常；保留可恢复 unit 副本及状态记录。已确认对象可移入 root 私有隔离位置，回滚时恢复原路径、权限和启用状态并重新加载对应 systemd manager。配置或 unit 若含认证，只留在服务器私有位置，不读取或导出其值。

同盘隔离不释放磁盘。永久释放数据目录需另行明确删除授权，不能自动上传或打包其认证与历史。整个 `.nvm`、Node 运行时、共享 pnpm store、其他工具、网站发行与备份不在删除范围内。实际包已确认是 `openclaw@2026.3.8`，位于 `/root/.local/share/pnpm/global/5/.pnpm/openclaw@2026.3.8_@napi-rs+canvas@0.1.96_@types+express@5.0.6_hono@4.12.7_node-llama-cpp@3.16.2/node_modules/openclaw`，约 205M。全局 `package.json` 的 `dependencies.openclaw` 为 `2026.3.8`。清理后的实际磁盘与内存增量重新测量，硬链接可能令目录大小不同于释放量。

### 包卸载与数据删除的边界

目标机 pnpm 为 10.31.0。本地同版本隔离实验发现 `remove` 拒绝直接传入 `--ignore-scripts`、`--ignore-pnpmfile` 和 `--global-bin-dir`。改用 `--config.*` 后，实际移除了合成 `openclaw`，保留另一全局工具与入口，包脚本标记未触发。验证使用本地 Node 24.16.0，目标机为 Node 22.22.1，尚未运行远端 pnpm。

最终候选参数如下，使用前须锁定服务器的准确 Node/pnpm 入口、store 与全局目录。`GLOBAL_DIR` 是包含版本目录 `5` 的父目录，不能写成 `.../global/5`。

```text
NODE PNPM_CJS remove --global openclaw
  --global-dir GLOBAL_DIR --store-dir SHARED_STORE
  --config.global-bin-dir=GLOBAL_BIN
  --config.ignore-scripts=true --config.ignore-pnpmfile=true
```

这些是参数占位说明，不是可直接复制的服务器命令。`GLOBAL_BIN` 还必须在该子进程 `PATH` 中，不修改 shell 启动文件。实验及失败证据在 `work/engineering/2026-10-23-parallel/pnpm-proof/`，最终 `result.json` 为 passed。依据为 [pnpm 10.x remove](https://pnpm.io/10.x/cli/remove#--global--g)、[ignoreScripts](https://pnpm.io/10.x/settings#ignorescripts) 和 [ignorePnpmfile](https://pnpm.io/10.x/pnpmfile#ignorepnpmfile)。

全局登记路径为 `/root/.local/share/pnpm/global/5/package.json` 和同目录 `pnpm-lock.yaml`。执行前在服务器私有位置保留可恢复登记、unit 和入口，并保留已确认包与共享 store，或验证准确版本的重新安装路线。仅复制 manifest 和 lock 不能保证依赖可恢复。恢复材料不导出真实认证，不运行共享 store 清理，不删除其他全局包。

卸载后核对登记移除、服务停驻、CLI 不再可用，并复查网站及其他站点。只有获准永久删除 `/root/.openclaw` 后才释放这部分数据空间；同盘隔离只提供回滚，不应报告为已释放 4.1G。

## 网站切换清单与回滚

以下是执行顺序，尚未获得本轮生产操作授权。最终 unit 内存、CPU、磁盘预算及负载范围必须随目标配置列出，不能直接套用当前 512 MiB worker 上限运行八路。

1. 记录旧发行、unit 配置和数据根身份，核对其他站点。保留旧 wheel、旧环境与原数据根。
2. 停止接收新任务，等待现有转换完成，再停止 web 与 worker。核对独占锁已释放、没有活动转换及 guardian。
3. 使用旧发行备份并核验 v1 快照。确认备份、恢复副本、八路完整临时预留及空闲底线均有空间，空间不足先停止操作。
4. 将准确 wheel 安装到新发行独立环境。用 `upgrade-v1` 将已核验快照恢复到不存在的新数据根，保留原完成时间和期限。
5. 在不开放新提交的条件下，验证新库、全部有效预览/PDF、原期限、受管身份和维护锁。不得以新程序直接覆盖旧库。
6. 经批准调整 worker 并行度与服务资源参数，再执行批准范围内的目标机独占、2、4、8 路测试。记录排队与处理时间，确认其他站点正常；不以本地合成结果替代此步骤。
7. 验收通过后恢复入口；失败时停止新服务，切回旧发行、旧 unit 与原数据根，再核对结果与其他站点。

开放新提交前完成回滚演练。开放后新库产生的任务与结果不得通过切回旧库静默丢弃；需要先停入口并保留新根，再决定恢复或交付方案。旧备份、旧发行与两份数据根在单独批准前保留。
