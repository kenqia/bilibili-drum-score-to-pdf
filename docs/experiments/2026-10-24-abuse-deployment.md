# 防滥用版本正式部署

2026-10-24，用户明确要求“push，然后部署”。已将当前分支 `codex/parallel-conversions` 推送至 origin，再完成正式服务从 schema v2 到 v3 的切换，没有创建 PR、合并 main、购买资源或修改 nginx、TLS、DNS 及其他服务。

推送时 HEAD 为 `4162616`，其中应用代码对应 `9d70e83`；两者之间仅增加一份 YouTube 获取实验文档，不影响已验证 wheel。防滥用功能的 212 项本地回归、双轴审阅和构建结果见[本地验证记录](2026-10-24-abuse-prevention.md)。本轮未修改程序源码，不重复完整回归。

## 安装和切换

新发行位于 `/srv/drum-score/releases/abuse-18534ac519e22e03`。wheel SHA-256 为 `18534ac519e22e039425e3c7281e85af1920f9387b85b9bdcd19d49157cbd3d2`。使用既有 wheelhouse 和准确版本约束离线安装，未修改系统 Python 或旧环境。目标机核对二十九个包文件、固定 BBDownNext 二进制 hash 及依赖一致性，`pip check` 通过。

在独立数据根 `/var/lib/drum-score-restore/abuse-v3-preflight-20261024` 中验证每日一百次、重启额度保留、暂停重试、恢复接收，以及可控时钟下的三十天身份清理。该测试不代表实际等待了三十天，不使用生产任务或真实认证。

预检时正式 v2 数据根无未完成任务。保存两份原 `90-parallel-budget.conf` 和旧 current 目标后，停止 web 接收、确认 worker 已排空，再停止 worker。用匹配旧发行创建并核验快照：

`/var/backups/drum-score/backup-before-abuse-20261024-090129`

通过新维护入口 `upgrade-v2` 恢复到原先不存在的 `/var/lib/drum-score-restore/abuse-v3-20261024`。原二百零二条记录的 `completed_at`、`expires_at` 完全一致，不延长期限。恢复副本的受管文件重新登记身份。旧根 `/var/lib/drum-score-restore/parallel-v2-20261023` 和旧发行 `/srv/drum-score/releases/parallel-ddfdc74a999e4694` 保留原地。

仅更新 web/worker 两份 profile 的数据根及对应注释，原资源参数不变。原子切换 current 后，正式 web 先监听本机 8792，worker 暂不启动，防止额度与取消试验触发实际获取。私有验收后才启动真实转换，最后撤销本次临时端口覆盖，重新加载 systemd 并将 web 恢复到 8791。

流程从北京时间 17:01:29 开始，17:04:04 完成首轮公网核验。维护窗口内入口暂时不可用，不计作普通请求可用率。

## 验收结果

私有 HTTP 在最终发行、正式 unit 和 v3 数据根上完成以下验证：

| 检查 | 结果 |
| --- | --- |
| 十次提交后取消，第十一次再提交 | 429 `submission_limit`，等待秒数与 `Retry-After` 一致 |
| 新提交和显式重试共同计数 | 第十一次入队尝试被拒绝，取消不退次数 |
| HTTP 重启 | 原额度保持有效 |
| 暂停、恢复接收 | 暂停拒绝新提交与重试，查询和取消继续；恢复后可入队 |
| 两个真实在线转换 | 2/2 complete，整轮约 123.108 秒 |
| 实际运行重叠 | 120.651 秒，保留八路配置，本轮只重新验收两路 |
| 暂停期间合法结果访问 | 查询、PDF、全部预览正常，六个文件 hash 匹配 |
| worker 内存峰值 | 434769920 字节，约 415 MiB |
| cgroup 事件 | high、max、oom、oom_kill 均为 0 |
| 其他服务 | nginx 和 zju-search 均保持 active |

真实转换使用既有公开来源，不替换匿名获取或转换实现；结果仍为 `reliable=false`，没有新做看图或音乐逐符号校对，不保证任意八个复杂视频都成功。

开放后，服务器侧首轮十次 HTTPS 首页探针全部为 200，最慢约 68 毫秒；WSL 独立探针为 200，约 213 毫秒。随后从公网接口提交新验收任务，查询与取消成功，最终状态为 cancelled。再进行二十次 HTTPS 探针，全部为 200，最慢约 20 毫秒。

收尾确认 schema 为 3、暂停状态为 0、web 和 worker 无自动重启，临时 8792 覆盖已撤销。worker 仍为 MemoryMax 1 GiB、CPUQuota 150%、TasksMax 256、FD 1024，web 仍为 MemoryMax 128 MiB、CPUQuota 50%。最终库中为 123 complete、13 cancelled、72 expired、9 failed，无未完成任务，磁盘可用约 10.12 GB。记录数量包含本轮新增验收任务及正常到期变化，不作为自然用户使用量。

## 保留材料和回滚

服务器新发行中的 `installation.json`、`deployment.json` 和 `rollback/` 保留安装身份、阶段时间、旧 profile 及原 current 目标。旧发行、旧数据根、完整 v2 核验快照和隔离预检根均保留。本轮未触发回滚。

公网开放前失败时，脚本只按本次登记的文件身份和 hash 撤销端口覆盖、恢复原 profile、切回旧 current 及旧数据根；排空超时时仅恢复旧 web，不停止仍在处理用户任务的 worker。公网开放后若失败，先暂停接收并保留新根，不自动切回旧库丢弃新任务。

本地证据位于 `work/engineering/2026-10-24-abuse-deploy/`，包括 `prepare.py`、`prepare-result.log`、`deploy.py`、`deploy-result.log`、`deployment.json`、`final-check.py` 和 `final-state.json`。验收创建的能力凭据只在进程内使用，不写入报告，不读取既有用户任务凭据或机器认证。

本轮仍未增加全站每日额度，也未新增入口洪泛防护、依赖漏洞扫描或系统出网隔离，不能将部署成功当作完整防入侵保证。
