# 停服备份、核验与恢复

`drum-score-maintenance` 在 Ubuntu/Linux 上备份任务数据库和已决定完成的结果，并恢复到新目录。工具使用标准库，不启动 HTTP、worker 或转换进程，不迁移未知 schema。先安装匹配发行包，保存 wheel、依赖和运行参数。部署与切换步骤见[部署指南](deployment.md)。

## 准备维护窗口

停止同一数据目录的 HTTP 和 worker，确认旧进程树已退出。`--services-stopped` 是操作者声明，不能证明 HTTP 已停。备份还取得原 `worker.lock` 的非阻塞锁，并在独立连接持有 SQLite `BEGIN IMMEDIATE` 写屏障。锁忙或数据库写忙时失败，不替换锁文件。误留 HTTP 的写事务会返回 503，因此仍应真正停服。

备份包含任务身份、能力摘要、来源、提交计数、暂停状态及结果，应与服务数据一样私有。工具新建目录为 0700、文件为 0600，不提供加密或签名。SHA-256 检查完整性，不能证明备份来自可信的人。

## 创建并核验备份

`--output` 指向不存在的目录，父目录必须已存在。来源、目标及祖先不能经过符号链接，来源与目标不能互相包含。示例中的 `/srv/drum-backups` 应预先建立为运营者的私有目录。

```sh
drum-score-maintenance backup \
  --data-root /var/lib/drum-score \
  --output /srv/drum-backups/snapshot-new \
  --services-stopped
drum-score-maintenance verify --backup-root /srv/drum-backups/snapshot-new
```

成功输出 `status=complete` 的 JSON，退出码为 0。失败输出脱敏错误，退出码为 2，不输出来源 URL、任务凭据、完整路径或原始异常。`files` 与 `bytes` 统计清单声明的数据库和结果文件，不含 `snapshot.json` 自身。

备份使用 SQLite backup API 得到一致数据库，再复制 `complete` 和 `finishing` 对应的 PDF、全部预览和结果 manifest。工具核对受管目录与文件身份、结果摘要和实际 SHA-256。预览沿用 manifest 的实际文件名和顺序，支持 pdftoppm 在 10 页以上使用的 `page-01.png` 等补零页名；页号必须从 1 连续递增，不重命名已发布文件。`queued` 和未决定完成的活动任务只保留数据库元数据，不复制视频、暂存或其他不完整产物。来源中的未知文件不进入备份，也不由备份操作删除。

`snapshot.json` 记录格式版本、schema、备份时间、包版本、包源码内容指纹，以及逐文件的相对路径、字节数和 SHA-256。核验检查实际目录与声明完全一致、SQLite 完整性、已知 schema、任务字段及结果引用。额外文件、空目录、重复声明、路径逃逸、符号链接、硬链接和特殊文件均拒绝。不要向完整备份目录追加说明文件。

## 恢复并启动正式服务

恢复前停止服务，选用新的数据目录：

```sh
drum-score-maintenance restore \
  --backup-root /srv/drum-backups/snapshot-new \
  --output /var/lib/drum-score-restored
```

工具先完整核验，再向私有暂存目录复制，为自己创建的完整结果登记新的 device/inode/ctime。它保留任务 ID、能力摘要、队列次序、原 `completed_at` 和原 `expires_at`，不延长结果寿命，也不复制旧 worker 锁。旧临时文件所有权不带入新目录。

将 web 和 worker 的 `--data-root` 切换到新目录，启动匹配发行版本。首次正式 worker 恢复把遗留 `running/cancelling` 标为 `interrupted`，继续原队列，核验已保存的 `finishing` 决定，并清理到期结果。恢复本身不执行这些业务动作。恢复期间跨过期限的结果仍沿用原期限，不能因此重新开放访问。

回滚时停服，切回保留的旧发行环境和配套数据。不要让旧程序打开未知 schema，不覆盖原数据，也不要把普通复制后的旧 inode/ctime 当作恢复完成。删除旧环境、备份或数据前另行确认保留决定。

## 设置资源边界

备份、核验、恢复和升级命令共享以下选项，参数必须为有限正数，`--max-files` 为不超过 100000 的整数：

| 选项 | 默认值 | 约束 |
| --- | --- | --- |
| `--timeout` | 60 秒 | 同一次核验、复制、复验和发布的总期限，SQLite 等待也受限。 |
| `--max-mib` | 4096 | 逻辑文件字节上限，完整备份核验包含清单自身。 |
| `--max-files` | 8192 | 文件与遍历目录条目数上限，也限制任务查询数量。 |
| `--min-free-mib` | 2048 | 创建和复制目标时保留的文件系统可用空间底线，只读 verify 不写目标。 |

数据库物理和逻辑大小另限 64 MiB，单个 JSON 限 16 MiB，目录深度限 8。复制前后检查文件身份、大小及时间，变化时拒绝发布。这些额度不是文件系统硬配额。

## 处理失败和残留

工具在目标旁创建随机 `.drum-maintenance-*` 私有暂存。复制文件和嵌套目录逐级 fsync 后，才排他 rename 发布，已有目标不会被覆盖。普通失败只清理本次登记身份的暂存目录，清理另限 5 秒和 32768 条目。

SIGKILL 或断电可能留下私有暂存目录。`verify` 和 `restore` 拒绝直接使用这些目录，重跑创建新暂存，不接管旧残留。不要通过改名把它冒充完整备份。先核对记录和没有活动维护进程，再由运营者决定残留处置。

`cleanup_incomplete` 表示安全清理未完成，`residue_name` 只提供本次随机目录名。工具不删除替换目录，不越过链接，也不接管旧残留。

`publication_durability_unknown` 且 `output_published=true` 表示排他 rename 已完成，随后父目录 fsync 失败。完整输出仍保留，先运行 `verify` 并核对文件系统状态。不要重试覆盖或声称掉电后一定持久。此边界采用故障注入验证，不代表真实断电验收。

## 整服务树终止后的暂存恢复

转换先创建空的私有 `.drum-score-job-*` 根，再于启动任何子进程前，在已有 `managed_attempts` 中持久登记 ownership marker 和根身份。即使 worker、转换进程和 guardian 一起被杀，新 worker 取得服务锁后也能清理身份匹配的确切私有根。根内转换暂存由该根的所有权覆盖。未知同前缀根、attempt 外文件、替换根或替换 marker 保留，不扫描接管。

该协议不改变 schema 版本。仅杀 worker 的 guardian 清理、整树 SIGKILL 恢复、marker 和根替换的保留行为分别验证，不代表目标主机 cgroup/OOM 已验收。

## 从旧快照升级防滥用版本

当前程序要求 schema v3，不自动打开或迁移 v1、v2 数据。先在维护窗口用匹配旧 schema 的发行完成停服备份和 `verify`，保留原发行与原数据根。新版本的普通 `verify/restore` 仍拒绝旧 schema，按快照版本选择专用入口。v2 示例：

```sh
drum-score-maintenance upgrade-v2 \
  --backup-root /var/backups/drum-score/VERIFIED_V2_SNAPSHOT \
  --output /var/lib/drum-score-restore/NEW_V3_ROOT \
  --timeout 60 --max-mib 4096 --max-files 8192 --min-free-mib 2048
```

将占位路径替换为实际已核验快照和不存在的新目录。v1 快照使用 `upgrade-v1`。命令严格核对对应旧 schema、清单、hash 和全部结果，复制到私有暂存根后，在副本中增加提交计数、暂停控制及索引；v1 还移除单活动索引。工具重新登记新文件身份，再排他发布 v3 数据根。源快照不变，任务、能力摘要及原完成/到期时间不变；未知 schema、已有输出和损坏文件拒绝发布。升级回执报告新 schema，不把旧库 hash 当作新库 hash。

旧版本没有完整的历史提交事件，升级后提交计数为空、接收任务默认开放，不根据任务的最后重试时间猜测历史次数。上线前如需保持暂停，先在新根运行下方暂停命令。v3 同版本备份恢复则原样保留计数和暂停状态；恢复过旧快照可能丢失备份之后的计数，因此上线须使用停服窗口的一致快照。

升级本身不切换运行数据根、不启动服务，也不购买资源。服务器切换须按具体授权执行。切换前等待原活动任务完成、停止 web 与 worker，核验新发行、新数据、全部预览及原期限；失败时切回保留的旧发行和旧数据根。旧程序不能读取 v3。切换后新任务的保存需要单独处理，不能覆盖或合并两库。

## 暂停和恢复接收任务

使用匹配 v3 的发行，以有权读写专用数据根的服务用户或运营者身份运行。命令只修改既有数据库中的接收状态，不创建数据根，不启动服务，不要求停止 worker，也不提供 HTTP 管理接口。

```sh
drum-score-maintenance pause-submissions --data-root /var/lib/drum-score
drum-score-maintenance resume-submissions --data-root /var/lib/drum-score
```

将数据根替换为实际运行目录。第一条暂停新提交和显式重试，第二条恢复接收，作为撤销暂停的操作。回执中的 `paused` 表示已持久保存的状态；失败退出码为 2，不能据此声称状态已改变。命令与入队共用 SQLite 写事务屏障，在暂停提交前已入队的任务继续执行。查询、取消、预览、PDF 仍遵守原凭据与期限规则。重复执行同一命令保持相同状态，重启不解除暂停。

这两条命令只接受 `--data-root`，不使用备份的资源选项。未知 schema、缺失数据库或符号链接路径均拒绝；在线备份屏障占用数据库时可能失败，待维护完成后再试。
