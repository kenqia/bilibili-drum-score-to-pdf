# 本地运行匿名鼓谱网站

YouTube 的 Deno 安装、代理、支持格式及失败限制见 [YouTube 获取](youtube.md)。新增代码尚未部署到正式网站。

网站代码接受公开 HTTPS B站 BV、b23.tv 和 YouTube 单视频链接，将任务交给独立 worker，完成后显示全部 A4 预览并提供 PDF 下载。无需账号或邀请码。网页不支持本地上传，不调用模型。`complete` 表示完整产物已发布，结果仍为 `reliable=false`，未经音乐校对。

本页面向 Ubuntu/WSL 上的运行与集成验证。2026-10-24，正式站点已完成防滥用 v3 切换，目标机配置、验收及保留材料见[部署记录](../experiments/2026-10-24-abuse-deployment.md)。其他主机仍须独立验证资源硬限制、代理和公开部署。

## 安装并启动

需要 Python 3.12 或更新版本，以及 `PATH` 中的 `ffmpeg`、`ffprobe` 和 `pdftoppm`。使用独立虚拟环境安装可选 `web` 依赖：

```sh
python3.12 -m venv /tmp/drum-score-web-env
/tmp/drum-score-web-env/bin/pip install '/absolute/path/to/bilibili-drum-score-to-pdf[web]'
/tmp/drum-score-web-env/bin/pip check
```

安装包含 FastAPI 0.156.8、Uvicorn 0.54.0 与现有转换依赖。HTTPX 0.28.1 仅用于测试。CLI 安装不引入可选网站依赖。安装包包含页面资源，运行不依赖源码工作目录。

1. 选择一个专用数据目录。目录不能经过符号链接，不要使用已有用户资料目录。
2. 在第一个终端启动 HTTP 服务：

   ```sh
   /tmp/drum-score-web-env/bin/drum-score-web \
     --data-root /absolute/path/drum-score-data --host 127.0.0.1 --port 8000
   ```

3. 在第二个终端启动独立 worker，使用同一个数据目录：

   ```sh
   /tmp/drum-score-web-env/bin/drum-score-worker \
     --data-root /absolute/path/drum-score-data
   ```

4. 打开 `http://127.0.0.1:8000`，提交公开 BV 链接，保存返回的完整任务链接。
5. 等待完成，检查全部预览与警告，再下载 PDF。关闭网页或重启 HTTP 服务后，worker 继续处理。

也可运行 `python -m drum_score.web` 和 `python -m drum_score.worker`。worker 的 `--concurrency` 支持 1 至 8 路，默认 1；`--once` 即使配置八路也处理至多一个任务后退出；`--poll-interval` 默认 0.25 秒，允许 0.01 至 60 秒。转换继续使用共享核心默认的600秒总期限、256 MiB输入、1 GiB采样RSS和1 GiB临时文件预算。这些采样预算不等于 cgroup 或文件系统硬限额。

连续采样与尾帧共享累计 600 秒解码预算，不再各自额外限制为 60 秒。监督进程仍独立执行整个任务的 `--timeout`，包括获取、采样与发布；扩大总期限不会取消累计解码或内存、磁盘上限。接受更慢不代表任务可以无限运行。

## 任务链接与隐私

任务链接使用 `/task/<id>#<capability>`。ID 和256位随机能力凭据独立生成，SQLite 只存凭据 SHA-256，服务以恒定时间比较摘要。浏览器从 fragment 读取凭据，通过 `Authorization: Bearer` 调用接口。任务状态、预览、PDF、取消和重试全部需要凭据；错误凭据与不存在的任务统一返回404，不提供任务列表。

链接具有读取和操作权限。只向可信的人分享，并保存包含 `#` 后内容的完整链接。浏览器不将凭据写入 Cookie 或 localStorage。页面与脚本同源，不加载第三方资源；响应设置 CSP、`no-referrer` 和 `no-store`。HTTP 入口禁用访问日志，不记录认证头、请求体或含凭据的提交响应。不要在反向代理或调试工具中另行开启这些内容的记录。

IP 只用于入队限流，不证明所有权。SQLite 保存规范化地址的 SHA-256，用于识别同一网络的未完成任务及滚动提交额度，这不表示匿名化保证。

## 队列、取消与恢复

同一 IP 最近 10 分钟最多成功入队 10 次，最近 24 小时最多 100 次。新提交和显式重试共同计数，取消及入队后的转换失败不退次数；格式错误、队列或资源不足等拒收入队不计数。检查额度、计数和任务写入共用写事务，重启不重置计数。超额返回 429 `submission_limit`，JSON 的 `error.retry_after_seconds` 和 `Retry-After` 头给出再次尝试所需的等待秒数；等待结束仍需满足未完成任务和资源限制。校园网、公司网络共享出口 IP，也共享提交额度。不提供邀请码或验证码放行，不设置全站每日提交额度。

运营者可通过本机维护命令暂停新提交和显式重试，返回 503 `submissions_paused`。既有队列、运行任务、取消、查询和合法下载继续工作。暂停状态跨进程、重启及同版本备份恢复保留，不新增公开管理接口，命令见[维护指南](maintenance.md#暂停和恢复接收任务)。

全站最多 10 个 `queued` 和 `--concurrency` 个活动任务，默认一个，最多八个。每个IP最多1个未完成任务，包含 `queued`、`running`、`cancelling` 和 `finishing`。校园网或公司网络可能共享名额。入队、显式重试与领取使用短 `BEGIN IMMEDIATE` 事务；部分唯一索引限制未完成 IP；同一领取事务检查全站活动数。状态、取消轮询与发布查询使用只读事务，同一调度器内的短事务由本地锁协调；SQLite 锁等待最多 1 秒，HTTP 忙时返回可重试的 503。调度器清理或领取轮询遇到 `service_busy` 会重试，不因此终止已有转换。

HTTP 提交仅校验短链接格式，不访问外部网络。短链接在 worker 的 `downloading` 阶段展开；排队和失败时 BV、分 P 为 `null`，网页显示分享短链接。完成摘要中的 `source` 为核验过的 BV 来源。分享跟踪参数不入库，重试会重新展开原短链接。

worker 按入队时间和ID领取最早任务。唯一调度器持有本机 `flock`，有界监督线程各自调用独立转换进程。启动恢复只执行一次，运行中的暂存恢复只处理刚停止的 task/attempt。每个 guardian 继承相同锁租约，直到全部任务树停止才允许接管。意外启动第二个 worker 时退出码为2，不重复领取。转换仍由共享 `drum_score.convert` 的真实子进程执行。

| 当前状态 | 取消或重启行为 |
| --- | --- |
| `queued` | 取消直接变为 `cancelled`；worker 重启后继续排队。 |
| `running` | 取消先变为 `cancelling`，进程树停止且暂存清理后才变为 `cancelled`。 |
| `finishing` | 完成决定已持久保存，后续取消不删除结果。 |
| `complete` | PDF与全部预览可读，重复取消保持完成。 |
| `failed`、`cancelled`、`interrupted` | 用户可显式重试，重新检查当前IP与全站配额，创建全新 attempt。 |

worker 收到 SIGTERM 会停止当前处理并退出；与HTTP取消同时发生时也不会继续领取下一个任务。SIGKILL 后，guardian 继承同一文件锁，只有真实进程树停止并完成清理后才释放。若 guardian 也同时终止，新 worker 按持久 ownership marker 和目录身份清理已登记的确切私有暂存根，未知根与替换物保留。新 worker 取得锁后恢复遗留任务，旧 `running/cancelling` 转为 `interrupted`，不静默重跑。

核心首先排他发布到私有 attempt 的 `result` 目录。worker 校验PDF、全部预览的字节数和SHA-256、清理原生帧及长图并更新manifest后，持久保存 `finishing`、摘要、原始完成时刻和到期时刻，再变为 `complete`。HTTP只发布 `complete`。这个数据库决定是取消与完成的顺序点，不再移动目录来制造第二个发布窗口。提交回执丢失时保留决定和文件；重启验证 `finishing` 的同一目录并恢复完成，不刷新保留期。缺失或损坏的决定不能发布为完整结果。

## 期限与下载

完成结果的访问期限为完成后24小时。状态、预览、下载、取消和重试共用持久 `expires_at`，到期返回410。尚未执行物理清理也不再允许新读取。到期后请重新提交来源链接。

下载在短事务内认证、检查期限并实际打开白名单文件，使用 `O_NOFOLLOW` 遍历服务私有目录。响应从打开的文件描述符分块读取，不持有长数据库事务。Linux下，已经合法打开的下载可在文件被unlink后继续读完；新的请求仍受期限限制。首块发送前断连、传输中断和正常结束都会关闭描述符。

页面通过认证 fetch 加载全部预览，再建立 Blob URL。PDF同样通过认证fetch下载，页面限制为256 MiB。Blob会占用浏览器内存，手机上的大文件仍需实际验收。页面离开时撤销预览Blob，浏览器从后退缓存恢复时重新查询状态与加载页面。

worker 启动及每轮领取前清理到期文件，默认轮询间隔0.25秒。HTTP只验证期限和打开文件，不执行物理删除；worker 停止期间到期仍拒绝访问，恢复后继续清理。已授权打开的FD可读完，断连后关闭；逻辑字节扫描不计已unlink但仍打开的FD，磁盘空闲检查仍能观察其占用。应用和代理仍需控制连接资源，不能把FD协议当成目标主机慢连接验收。

线上仅保留 PDF、全部预览与 manifest。获取视频和处理中间文件随任务结束清理；原生 samples 与 longshot 引用改为 `original_path`、`retained=false`，保留实际 PTS、hash和处理记录。`retention.can_reconstruct_from_retained_sources=false` 明确不能仅凭剩余文件重建。CLI 的实验留存不使用此线上策略。

失败、取消及中断任务默认保留1小时，诊断仅含脱敏错误码和信息，文字全局上限8MiB。超过文字额度的旧诊断清空，任务仍可在期限内显式重试。到期清空来源、结果摘要及错误文字，身份在原到期时刻后再保留 30 天，供合法旧链接返回 410。此后 worker 执行正常受管文件清理并删除任务身份与其受管登记，所有任务接口返回 404。worker 停止期间不执行物理删除或记录清理。未知文件和身份已替换的文件不会接管或删除，其占用仍计入任务目录额度；三十天后仍有残留时需运营者核查。

## 存储参数与 schema

以下参数由 web 和 worker 共同使用。两个进程应显式使用相同参数；改变部署参数前停止服务并保存匹配的完整副本。

| 参数 | 默认 | 实际含义 |
| --- | --- | --- |
| `--retention-seconds` | 86400 | 结果从持久完成时刻开始的保留期，重启不刷新。 |
| `--diagnostic-seconds` | 3600 | 失败、取消、中断的保留期。 |
| `--diagnostic-mib` | 8 | 全局错误文字额度。 |
| `--min-free-mib` | 512 | 文件系统可用空间底线。 |
| `--retained-mib` | 4096 | attempts目录全部普通文件的逻辑字节总额，含结果、运行暂存与未知文件。 |
| `--max-temp-mib` | 1024 | 单次转换临时额度，同时是准入预留量。 |

入队、重试及worker领取要求 `used + (active + 1) * max_temp <= retained` 且空闲空间至少 `min_free + (active + 1) * max_temp`，其中 active 包含 `running/cancelling/finishing`。全额预留与已落盘字节重复计入，偏保守；预留检查和领取处于同一事务。活动预留耗尽时领取保留任务排队；无活动任务仍空间不足则记录 `storage_full` 失败。运行时约每200ms检查 `used <= retained` 和空闲底线，超额以 `storage_full` 明确失败并停止进程树，不删除未到期结果。若总额和预留都设1024MiB，第一份结果之后将拒收，直到结果到期；总额2048MiB允许约1024MiB留存结果和1024MiB执行预留。数值为逻辑字节，稀疏文件、数据库及已打开删除文件仍由空闲检查兜住，采样不等同硬配额。

worker另接受 `--timeout`、`--max-input-mib`、`--max-rss-mib`，默认600秒、256MiB、1024MiB。`--max-temp-mib`也传入核心资源预算。当前默认值是本地候选，目标2GB主机需按现有服务余量实测及硬限额验收后使用。

SQLite 的 `PRAGMA user_version=3` 是当前服务 schema，包含持久提交计数和暂停状态。旧库和未知版本拒绝启动，不自动迁移任务。v1、v2 备份分别用显式 `upgrade-v1`、`upgrade-v2` 恢复到不存在的新目录并升级，源快照保持原样，见[维护指南](maintenance.md)。`managed_attempts` 保存受管根 device/inode及文件相对路径、device/inode/ctime。清理从数据根逐级打开 no-follow 目录FD并核对身份，只删除已登记文件；目录只在空时删除，符号链接和替换物保留。丢失或无法安全确认的材料宁可保留，随后计入容量并由运营者核查，不扫描其他服务目录。

备份恢复须同时保存数据库、结果和准确发行版本。复制到新目录会改变inode/ctime，恢复工具只可为经清单/hash核验且自己新建的文件登记新身份，保留原始completed_at/expires_at。直接恢复旧身份会阻止清理，不能当成完整恢复。停服备份与恢复使用 [drum-score-maintenance](maintenance.md)，配置与回滚步骤见[部署指南](deployment.md)。

## HTTP 接口

除提交外，以下接口都需要 `Authorization: Bearer <capability>`。请求体在JSON解析前限制为8 KiB，接收超过10秒返回408；拒绝响应不回显提交载荷。

| 方法与路径 | 行为 |
| --- | --- |
| `POST /api/tasks` | `{"url":"https://www.bilibili.com/video/BV…?p=2"}` 或 `{"url":"https://b23.tv/…"}`，成功201，返回ID、能力凭据及完整相对链接。 |
| `GET /api/tasks/{id}` | 返回真实状态、阶段、队列位置、来源、错误和完成摘要，无百分比或ETA。 |
| `POST /api/tasks/{id}/cancel` | 幂等取消，以持久完成决定为界。 |
| `POST /api/tasks/{id}/retry` | 显式重试失败、取消或中断任务，重新受入队配额限制。 |
| `GET /api/tasks/{id}/pages/{page}` | 读取从1开始的单页预览，不接受文件路径。 |
| `GET /api/tasks/{id}/pdf` | 下载PDF。 |

默认只使用ASGI真实对端，不信任 `X-Forwarded-For`。入口显式设置Uvicorn `proxy_headers=False`，防止它先重写对端地址。确认代理确实清洗并写入转发头后，可使用重复的 `--trusted-proxy IP` 配置精确IP；不接受 `*`。应用从右向左剥离已配置代理，只使用首个非可信地址，不把其左侧内容作为客户端身份。格式错误或超过16项的代理链返回400。正式反向代理和TLS部署需另行审阅与授权。

## 验证与回滚

在仓库根目录运行包含网站测试依赖的完整验证：

```sh
python -m pip install '.[web]' -r tests/requirements-web.txt
python -m unittest discover -s tests -v
```

网站专项为 `test_web`、`test_web_worker` 和 `test_product_lifecycle`。HTTP、Python、CLI的共同远端转换约束在 `tests/test_public_contracts.py`。测试只使用合成视频、随机测试凭据和外部匿名网络替身，不访问真实认证。进程测试在Linux验证 SIGTERM、SIGKILL、冻结guardian、重启、完成/取消顺序和提交回执丢失。合成成功不代替真实谱面或浏览器实际验收。

停止HTTP服务和worker后，可保留专用数据目录并切回独立旧checkout和虚拟环境。不要让旧版本打开未知数据库schema，不通过删除用户目录进行回滚。安装与页面资源变更仅在独立环境中生效，不改用户全局配置。

## 并行部署前提

仓库默认不表示生产已开放八路。web 和 worker 必须使用一致的存储预算；每任务 RSS 额度不等于整个 unit 内存额度，调度器、监督线程、所有转换树和 guardian 都计入 unit cgroup。八路不能沿用现有 512 MiB `MemoryMax`、100% `CPUQuota` 和 `TasksMax=64` 就宣称通过。目标配置与验收见[容量方案](capacity-plan.md)。

成功 manifest 的 `metrics.phase_seconds` 与交付摘要 `resources.phase_seconds` 记录准备、下载、探测、采样、配准、合成和分页的实际单调时钟耗时。它们不包含排队和最终监督器发布开销，不能与端到端等待混用。
