# 部署、备份与迁移

本指南面向现有 Ubuntu 24.04、2 核 2 GB 主机，域名为 `drum.kenqia.top`，不使用 Docker。先完成本地安装、恢复演练与审阅，再取得服务器写入授权。下面的服务器命令是待执行方案，本地验证不表示网站已经上线。

## 部署范围与前置检查

新增文件与目录如下。执行前核对它们未被其他应用占用；遇到已有对象时停止，不覆盖未知对象。

| 对象 | 用途与所有者 |
| --- | --- |
| `/srv/drum-score/releases/RELEASE_ID` | 独立发行文件、venv 和配置，root 管理，应用只读。 |
| `/srv/drum-score/current` | 指向已验收发行目录的链接，root 管理。 |
| `/var/lib/drum-score` | 专用任务数据，drum-score 用户，0700。 |
| `/var/backups/drum-score` | 私有完整备份，drum-score 用户，0700。 |
| `/var/lib/drum-score-restore` | 新目录恢复的专用父目录，drum-score 用户，0700。 |
| `/etc/systemd/system/drum-score-{web,worker}.service` | 本服务两个独立 unit。 |
| `/etc/nginx/sites-available/drum-score` | 本服务当前阶段的站点文件。 |
| `/etc/nginx/sites-enabled/zz-drum-score` | 在现有 zju-search 站点之后加载的新链接。 |
| `/var/www/drum-score-acme` | 独立 ACME webroot。 |
| `/etc/letsencrypt/live/drum.kenqia.top/` | 新域名自己的证书，由 Certbot 管理。 |

现有 `api.kenqia.top`、8787 后端、8080 staging、nginx 主配置，以及 zju-search 的 `/opt/zju-search`、`/var/www/zju-search` 和 `/var/lib/zju-search` 继续使用。mihomo、`/root/clash`、现有证书、`.openclaw` 和 `.nvm` 不在本次部署清理集合内。

已有 OpenClaw user service 的停止或删除另行确认。不要打包 root home、认证、私钥或其他服务的数据。备份工具只处理明确指定的本服务数据根。

部署前重新只读检查可用内存、磁盘、8791 端口、现有站点和默认 Host 的响应。此前约 869 MiB 可用内存和 8.63 GiB 可用磁盘只是盘点时快照。8791 未预留；确认无冲突后才使用。

DNS 方案是在 DNSPod 新增 `drum` 的 A 记录，值为 `118.25.26.140`。此前两台权威服务器返回 NXDOMAIN，不能当作部署时状态。由有域名控制权的人配置并核验权威结果；不要提供 DNS token。DNS 写入、证书签发、安装和服务启停均须取得相应授权。

## 资源候选与开放门槛

两个 unit 采用相同存储参数，worker 串行执行转换。

| 参数 | 候选值 |
| --- | --- |
| 完成结果保留 | 86400 秒 |
| 诊断保留 / 全局文字额度 | 3600 秒 / 8 MiB |
| attempts 全部普通文件总额 | 2048 MiB |
| 每次临时额度及准入预留 | 1024 MiB |
| 磁盘空闲底线 | 2048 MiB |
| 单视频 / 转换总期限 | 256 MiB / 600 秒 |
| worker RSS 采样额度 | 512 MiB |
| worker MemoryHigh / MemoryMax | 384 MiB / 512 MiB |
| web MemoryHigh / MemoryMax | 96 MiB / 128 MiB |
| worker / web CPUQuota | 100% / 50% |

准入要求 `used + 1024 MiB <= 2048 MiB`，且实际可用磁盘至少 3072 MiB。2048 MiB 是结果、未知文件及活动暂存的合计，不能全当成历史结果额度。空间不足时停止接收，不提前删除未到期结果。备份、恢复副本、发行文件及已 unlink 但仍打开的文件另占磁盘。

两个 unit 设置 `MemorySwapMax=0`、`OOMPolicy=stop`、`KillMode=mixed` 和 30 秒停止期限。内核 OOM 后停止本服务，失败重启不自动重跑中断任务。数值库线程环境为 1；解码器另有固定线程设置。应用采样和 cgroup 内存计量不同，WSL 的 RSS 测量不能代替目标机硬限额验收。

本地缺少可写 cgroup 和用户总线。2026-10-22 已在目标机完成沙箱及硬内存控制下的实际小星星转换，见[最新部署验收](https://github.com/kenqia/bilibili-drum-score-to-pdf/blob/8c8730a4c3defa2fb317897a648ebc3ef66b4273/docs/experiments/2026-10-22-bbdown-integration.md)。后续发行仍须重新评估变更风险。在目标机验证完整转换、重复任务、硬限额、清理、取消、重启、全部预览及下载，并复查既有网站后，才能开放公网服务。整棵服务进程树丢失后的临时文件恢复也必须通过，不能只验证 guardian 存活的情况。

## 安装独立发行

以下步骤仅在服务器写入获准后执行。`RELEASE_ID` 必须替换为经过验收的完整 Git commit。不要就地升级运行中的 venv。

1. 在本地从准确提交构建并验收 wheel 与 sdist，记录 SHA-256、依赖版本和全部配置 hash。迁移时同时保留这个 Git 提交的源码与本目录配置。后续通过正常 SSH/SCP 传输这些发行材料，不传输任何认证文件。
2. 在目标主机核对 Python 3.12 和现有 nginx，安装缺少的依赖。以下包安装会改变系统，须包含在授权范围内：

   ```sh
   apt-get update
   apt-get install --no-upgrade python3.12-venv ffmpeg poppler-utils fonts-dejavu-core certbot
   ```

   不重装 nginx，不升级其他网站的 Node 或 Python 环境。
3. 创建专属无登录用户和新目录。下面是首次安装命令，执行前确认用户名和目标路径未被占用：

   ```sh
   useradd --system --user-group --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin drum-score
   install -d -o root -g root -m 0755 /srv/drum-score/releases
   install -d -o drum-score -g drum-score -m 0700 /var/lib/drum-score /var/backups/drum-score /var/lib/drum-score-restore
   ```

4. 创建新的发行目录，将准确源码中的 `deploy/`、wheel、sdist、已验收的 `wheelhouse/`、`runtime-versions.txt` 和 hash 清单传入该目录。目录必须不存在；示例中的 wheel 文件须来自同一发行清单。核对上传 hash 后创建 venv 并安装：

   ```sh
   DRUM_RELEASE=RELEASE_ID
   mkdir "/srv/drum-score/releases/$DRUM_RELEASE"
   ```

   在本地执行 SCP，把上述发行材料传入这个新目录；再回到服务器执行：

   ```sh
   umask 022
   python3.12 -m venv "/srv/drum-score/releases/$DRUM_RELEASE/venv"
   "/srv/drum-score/releases/$DRUM_RELEASE/venv/bin/pip" install --no-index --find-links "/srv/drum-score/releases/$DRUM_RELEASE/wheelhouse" --constraint "/srv/drum-score/releases/$DRUM_RELEASE/runtime-versions.txt" "/srv/drum-score/releases/$DRUM_RELEASE/bilibili_drum_score_to_pdf-0.1.1-py3-none-any.whl[web]"
   "/srv/drum-score/releases/$DRUM_RELEASE/venv/bin/pip" check
   "/srv/drum-score/releases/$DRUM_RELEASE/venv/bin/drum-score-maintenance" --help
   ```

   同时按[安装指南](../install.md#安装公开链接解析器)核验并安装 BBDownNext 2.3.0 单文件到此发行的 `venv/bin/BBDown`，保留第三方 MIT 许可。它由 root 管理，应用只读。worker 模板的 PATH 包含当前发行的 `venv/bin`；不要安装到共享 Python，也不要导入代理订阅或凭据。新应用 0.1.1 的 Python 依赖已移除 yt-dlp，旧发行保持原样，便于回滚。

5. 从仓库外以 drum-score 用户运行合成 CLI、web 和 worker smoke，核对全部预览、实际 PTS 及依赖位置。保留证据，不能把此检查称为音乐校对。确认新发行只由 root 写入，再创建首次 `current` 链接：

   ```sh
   ln -s "/srv/drum-score/releases/$DRUM_RELEASE" /srv/drum-score/current
   ```

6. 将本发行的两个 unit 分别安装为上述 `/etc/systemd/system/` 文件，升级时先保存原有本服务 unit 的可恢复副本。执行 `systemd-analyze verify`，再 `systemctl daemon-reload`。首次启动时先核对实际 cgroup 控制可用，尚未验收前保持公网入口关闭。

   ```sh
   install -m 0644 /srv/drum-score/current/deploy/systemd/drum-score-web.service /etc/systemd/system/drum-score-web.service
   install -m 0644 /srv/drum-score/current/deploy/systemd/drum-score-worker.service /etc/systemd/system/drum-score-worker.service
   systemd-analyze verify /etc/systemd/system/drum-score-web.service /etc/systemd/system/drum-score-worker.service
   systemctl daemon-reload
   systemctl start drum-score-web.service drum-score-worker.service
   systemctl is-active drum-score-web.service drum-score-worker.service
   ```

   查看脱敏状态与资源指标，不导出请求体、Authorization 或原始网络异常。单位只获得本服务数据目录写权限。

## 接入域名与证书

1. 经授权配置 DNS 并核对权威 A 记录。先检查已有 api 域名、staging 和原 IP/default Host 的状态及响应。
2. 创建独立 ACME webroot，把 [HTTP 前置配置](../../deploy/nginx/drum-score-http.conf) 安装为 `/etc/nginx/sites-available/drum-score`，通过 `/etc/nginx/sites-enabled/zz-drum-score` 启用。不要加 `default_server`，不要修改既有站点。检查 `nginx -t` 成功后才 reload。

   ```sh
   install -d -o root -g root -m 0755 /var/www/drum-score-acme/.well-known/acme-challenge
   install -m 0644 /srv/drum-score/current/deploy/nginx/drum-score-http.conf /etc/nginx/sites-available/drum-score
   ln -s /etc/nginx/sites-available/drum-score /etc/nginx/sites-enabled/zz-drum-score
   nginx -t
   systemctl reload nginx
   ```

   仅在 `nginx -t` 成功时执行 reload。TLS 切换也遵循同一条件。
3. 从公网核对测试挑战路径可达。取得签发授权后执行：

   ```sh
   certbot certonly --webroot --webroot-path /var/www/drum-score-acme --domain drum.kenqia.top --cert-name drum.kenqia.top
   ```

   按提示由操作者提供账户信息。api 的现有证书只覆盖 api，不能拿来服务 drum。
4. 确认目标机资源和实际转换验收通过后，保存前置站点副本，用 [TLS 配置](../../deploy/nginx/drum-score-tls.conf) 替换本服务同一个站点文件。两份配置不能同时启用。`nginx -t` 后 reload，验证域名、完整证书链和 HTTPS 跳转，并复查 api、staging 和默认 Host。
5. 核对 Certbot timer 与该证书的续期配置。经授权执行 `certbot renew --cert-name drum.kenqia.top --dry-run`，确认更新后会成功 reload nginx，不能因为签发成功就宣称自动续期已通过。全部验收通过后执行 `systemctl enable drum-score-web.service drum-score-worker.service`，核验启动依赖与持久启用状态。

nginx 关闭本服务访问日志，覆盖 `X-Forwarded-For`，转发认证头。请求和响应都不缓冲；HTTP/1.1 使分块请求及时进入应用的累计 10 秒 body 期限。`client_body_timeout` 仅控制空闲间隔，不代表总期限。8 KiB body 限制、慢连接、FD 回收仍需在实际代理上验证。

## 完整备份

只支持维护窗口内的完整备份。工具不停止服务，`--services-stopped` 是操作者对停服前提的明确声明。工具另取 worker/guardian 原锁和 SQLite 写屏障；worker 锁本身不能证明 HTTP 已停止。

1. 停止本服务 HTTP，等待进程退出及活动下载连接关闭，再停止 worker。不停止 nginx 或其他应用。

   ```sh
   systemctl stop drum-score-web.service
   systemctl stop drum-score-worker.service
   systemctl is-active drum-score-web.service drum-score-worker.service
   ```

   两个状态应均为 inactive；此检查返回非零属于预期。若仍在 stopping 或锁被占用，先查明本服务状态，不删除锁文件绕过。
2. 选择不存在的目标。以本服务用户备份并核验：

   ```sh
   DRUM_BACKUP=/var/backups/drum-score/backup-YYYYMMDD-HHMMSS
   runuser -u drum-score -- /srv/drum-score/current/venv/bin/drum-score-maintenance backup --data-root /var/lib/drum-score --output "$DRUM_BACKUP" --services-stopped --timeout 60 --max-mib 4096 --min-free-mib 2048 --max-files 8192
   runuser -u drum-score -- /srv/drum-score/current/venv/bin/drum-score-maintenance verify --backup-root "$DRUM_BACKUP" --timeout 60 --max-mib 4096 --min-free-mib 2048 --max-files 8192
   ```

3. 保存脱敏成功记录、工具版本与完整发行 hash。完成后启动两个 unit，并核对状态。

备份含同一快照的 SQLite、schema 要求的 PDF、全部预览、manifest 和版本化清单。SQLite Backup API保证数据库内部一致；固定数据库文件集、锁和逐文件 hash 核验另保证产物集合一致。视频、中间图、锁 inode、SQLite sidecar、venv 和机器认证不在备份中。

备份可能含任务能力摘要和来源，按私有数据保存，不提供公开下载。SHA-256 是完整性核验，不能当成防篡改签名。已有任务完整能力链接继续使用；备份不能重新生成用户丢失的原凭据。

工具保持原完成和到期时刻。复制过程中跨过期限也不能遗漏快照所需文件；恢复后已到期的任务不会重新获得 24 小时。未知 schema、损坏或缺失结果、外部链接、额外文件及已有输出应明确失败，不发布半份备份。

若工具在排他发布之后无法同步父目录，会返回退出码 2、`publication_durability_unknown` 和 `output_published=true`。此时完整目标目录已存在，掉电持久性未确定；保留它并先运行 `verify`，不要用同一路径重试覆盖。失败清理不完整时，记录只含本次私有暂存目录名的 `cleanup_incomplete`，确认身份后另行处理。

工具有时间、逻辑字节、文件数与实际磁盘水位限制，不自动删除旧备份。保留一份已验证的最近完整备份；替换前先核验新副本，旧副本删除单独确认。容量规划必须同时计入运行数据、旧备份、新副本和恢复副本，空间不足时停止本次维护。

## 恢复与回滚

恢复工具只写不存在的新数据根，拒绝覆盖现存空目录和运行目录。源备份与目标不能嵌套。执行前再次停止本服务 HTTP 和 worker，并核验兼容的程序发行及 schema。

```sh
DRUM_RESTORED=/var/lib/drum-score-restore/recovered-YYYYMMDD-HHMMSS
runuser -u drum-score -- /srv/drum-score/current/venv/bin/drum-score-maintenance restore --backup-root "$DRUM_BACKUP" --output "$DRUM_RESTORED" --timeout 60 --max-mib 4096 --min-free-mib 2048 --max-files 8192
```

工具核验后仅为自己新建的文件登记新 device/inode/ctime，不照搬旧机器文件身份。保持任务 ID、能力摘要、顺序、完成及到期时间。正式 worker 启动时保留 queued，把遗留运行任务标记中断，验证 finishing 决定；不由恢复工具重跑任务。

恢复成功后，由管理员在维护窗口将旧数据根移到一个不存在的留存路径，再将新根移入 `/var/lib/drum-score`。保留旧根，不合并目录，不复制旧 `worker.lock`。核对实际文件所有者为 drum-score、新根身份正确和旧根仍在，再启动两个 unit，核验原能力链接、全部页及过期清理。这些路径切换属于另行授权的服务器写操作，工具不会自动执行。

代码回滚先停止本服务，再把 `current` 原子切回保留的兼容发行。先保存并核对旧链接目标，不能把真实目录当链接覆盖。schema 不兼容时同时使用匹配的完整数据备份，经上述新根恢复后切换；不要让旧代码试着打开未知 schema。回滚同样检查既有 api、staging 和默认 Host。

## 2027 年 3 月前迁移

至少在到期前两周演练迁移。准备源码提交、wheel/sdist 及 hash、经过验收的依赖版本和 wheelhouse、两份 unit、两阶段 nginx 配置，以及维护窗口生成并验证的完整数据备份。私钥和其他机器认证不随程序备份复制；在新主机为本域名正常签发证书。

在新 Ubuntu/Python 3.12 环境从 wheelhouse 安装相同依赖，从仓库外验证 CLI/web/worker。使用相同发行的维护工具恢复到新根，验证全部页及原期限，再验证目标机 cgroup、网络和 HTTPS。不要复制旧 venv，它包含机器相关路径。

切换期间只保留一个活动写入者。先停止旧主机本服务，制作最后完整备份，恢复并验收新主机，然后经授权切换 A 记录。保留旧机已停止的数据和发行作为回退；DNS 生效和已有下载连接分别核对，不能把 TTL 当成即时完成。回退先停止新机写入，再选择匹配的最后完整快照，明确切换后的新任务是否需要另行保存，不直接覆盖或合并两库。

## 验证状态

本地 unit 静态语法、独立 loopback nginx 及合成证书演练，与实际 systemd 沙箱、cgroup、服务器匿名下载、真实 TLS 和现有网站回归分别记录。最终证据见[验证指南](../verification.md)。没有服务器写入授权和目标机结果时，#74 与公开上线保持未完成。

## 可选的预算并行配置

默认 unit 保留一路和原资源预算。2026-10-23 的显式并行候选位于 `deploy/systemd/profiles/`，需要先核验新 wheel、完成 v1 快照到 v2 新根的恢复，再安装匹配的 web/worker drop-in。它扩大共享内存与进程数上限，保留总 CPU、Swap、磁盘和任务期限保护。不能只把 `--concurrency` 改为 8，也不能将 profile 直接用于旧库。配置值、私有验收端口、公开步骤和回滚见[并行切换候选](parallel-rollout.md)。当前正式服务未安装这些 profile。
