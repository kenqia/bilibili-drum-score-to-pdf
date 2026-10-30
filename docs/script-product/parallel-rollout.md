# 预算优先的八路并行配置

2026-10-23，用户明确批准本清单后，正式网站已切换到以下八路配置。此前已在现有机器完成八路真实在线转换，未购买套餐。代码默认仍为一路，生产通过显式 profile 启用八路。上线验收与保留材料见[正式切换记录](https://github.com/kenqia/bilibili-drum-score-to-pdf/blob/4d75de5/docs/experiments/2026-10-23-parallel-deployment.md)。

## 固定产物与资源

候选 wheel SHA256 为 `ddfdc74a999e4694662e6d92f7f692e61ba14e23b01856f61a4b38a37117fb92`。它包含有界调度器、schema v2 和连续解码期限修复，未改独立 Skill 或增加生产依赖。切换前核验 29 个包文件及公开解析器的固定 hash，不只根据同为 `0.1.1` 的版本名选择包。

| 项目 | 候选值 |
| --- | --- |
| 新发行目录 | `/srv/drum-score/releases/parallel-ddfdc74a999e4694`，独立环境，不修改旧发行 |
| 原发行 | `/srv/drum-score/releases/7fa75ac9a8aeaaa3cdea8b2ab9a58e0018235e2c` |
| 原数据根 | `/var/lib/drum-score`，保留原地，不用新程序打开它 |
| 新数据根 | `/var/lib/drum-score-restore/parallel-v2-20261023`，从核验的 v1 快照升级，必须原先不存在 |
| 同时执行 | 最多 8，不同 IP；同 IP 仍最多一个未完成任务，等待队列仍最多 10 |
| worker 共享内存 | MemoryHigh 896 MiB、MemoryMax 1 GiB、SwapMax 0 |
| worker CPU | 最多 150%，CPUWeight 10、IOWeight 10、Nice 10 |
| 进程与 FD | TasksMax 256、LimitNOFILE 1024 |
| 单任务 | 总期限 1200 秒、输入 256 MiB、采样 RSS 512 MiB、暂存 512 MiB |
| 解码 | 累计最多 600 秒，另受总任务期限约束 |
| 任务目录总额度 | 8192 MiB，至少保留磁盘可用空间 2048 MiB |
| web | 保持 MemoryMax 128 MiB、CPUQuota 50%；正式端口仍为本机 8791 |

所有转换共享 worker 的 1 GiB 硬限额，不能把八个单任务 RSS 上限相加当作可用内存。超出单任务预算会受控失败；触发共享 OOM 时 `OOMPolicy=stop` 停止整个 worker，重启后按现有协议处理受中断任务，web 与其他服务保持各自边界。该配置保护服务器资源，不保证任意八个高分辨率视频都能完成。

任务目录总额度是逻辑预算，不是预分配 8 GiB 文件。领取和准入保守预留活动任务空间，空间不足时等待或拒绝，不能提前删除未到期结果。如果八路真实验收不完整，不自动安装本配置或擅自降低用户目标。

## 已批准的操作清单

1. 复核当前发行、v1 schema、正式服务、共享工具、主机余量与磁盘；确认没有其他发布或维护。核对新的 drop-in 路径不存在。若有不同的运行状态或现有同名文件，停止并调整清单。
2. 在新发行目录准备独立环境和准确 wheel，核验与测量包一致的依赖、29 个文件与 BBDownNext。保留旧发行及现有配置，不修改 nginx、TLS、域名或其他站点。
3. 停止正式 web 接收新任务，等待当前 worker 排空，再停止 worker。维护期间公网可能短暂返回 502。无法在约定窗口排空时恢复旧 web，延期切换，不能强杀未完成任务。
4. 用保留的旧发行在 `/var/backups/drum-score/` 创建本次唯一 v1 快照并核验。核对原数据根和备份可恢复、恢复副本空间充分后，以新维护入口 `upgrade-v1` 恢复到表中新根。原完成时间和期限不刷新，新 inode/ctime 重新登记。已有输出、未知 schema 或核验失败时拒绝继续。
5. 将 worker、web 两份最终 profile 分别作为各自 service 的 `90-parallel-budget.conf`，并临时增加 web 的 `99-parallel-verify-port.conf`。清除继承的 `StateDirectory` 自动建目录行为，显式使用已经核验的新根；基本 unit、其他 drop-in 与原数据保持原地。记录新增文件内容 hash 和身份，供精确撤销。
6. 原子切换 `current` 到新发行，重新加载 systemd，启动新 worker 与监听 8792 的 web。公网 nginx 仍连接尚未开放的 8791。验证服务、v2 库、原期限与全部有效产物，并通过本机 8792 验证提交、同 IP 拒绝、状态、取消、完整 PDF/页面，以及至少两任务实际重叠。检查 cgroup 峰值、OOM、临时空间与其他服务。
7. 验收通过后，仅撤销本次临时 web 端口 drop-in，执行 `systemctl daemon-reload`，核对有效启动命令的数据根和端口，再重启 web 到 8791并复查公网 HTTPS。检查输出仅包含已知的非敏感参数，不输出完整环境。保留 worker 八路配置和最终两份 profile。交付实际容量边界及首次运行状态，不承诺未测输入规模。

profile 源文件位于：

- [worker profile](../../deploy/systemd/profiles/parallel-budget-worker.conf)
- [web profile](../../deploy/systemd/profiles/parallel-budget-web.conf)
- [临时私有验收端口](../../deploy/systemd/profiles/parallel-budget-web-verify.conf)

这些文件没有自动安装入口，默认部署模板仍保持一路。本轮收到网站切换的单独明确批准后，已按本清单安装两份最终 profile；私有端口 profile 在验收后精确撤销并执行 daemon-reload。后续变更按其实际影响另行确认。

## 回滚与保留

公开 8791 前失败时停止新服务，只撤销本次新增且身份/hash 匹配的 drop-in，原子切回原发行，执行 `systemctl daemon-reload`。核对有效启动命令使用旧数据根 `/var/lib/drum-score`、web 端口 8791 和原资源参数，再启动旧 web/worker。原 unit 和原数据根仍在原位置。保留失败新根、快照和新发行留证，不覆盖或合并两套数据库。

开放新提交后出现故障，先停止新入口和 worker并保留新根。不能切回旧库后静默丢弃新任务；先明确新任务的恢复或交付处理，再回滚。原发行、旧根、核验快照以及本轮恢复材料在另行决定前保留。

公网健康失败、文件/期限不匹配、OOM、未知 schema 或其他服务异常均停止开放或继续扩量。耗时超过独占两倍不再单独触发失败，但每任务总期限与资源保护继续生效。
