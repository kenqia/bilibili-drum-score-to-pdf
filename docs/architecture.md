# 鼓谱转换架构

仓库同时提供独立的 Skill 和程序/网站。入口与依赖边界见 [ADR 0007](adr/0007-independent-skill-and-website.md)。

## 两条产品路径

| 产品 | 运行边界 | 状态与交付 |
| --- | --- | --- |
| Skill | `skills/bilibili-drum-score-to-pdf/` 自带脚本和 references，不导入网站包。安装见 [Skill 指南](skill-install.md)。 | 独立任务 `record.json`、Agent 看图和版本绑定的终稿审阅；可选重绘/矢量按本包协议执行。 |
| 程序与网站 | `src/drum_score/` 由 `pyproject.toml` 打包，不加载 Skill。Python、CLI 与网站共用 `drum_score.convert`。 | CLI manifest 或网站 SQLite 队列/attempt；自动发布保持 `reliable=false`，不需要 Agent 审批。 |

Skill 按自己的 requirements 使用原有匿名获取工具；网站的 B站路径使用固定 BBDownNext 2.3.0 直连元数据入口，YouTube 使用网站独立的固定 yt-dlp、EJS 和 Deno。两套环境不互相安装依赖、共享任务目录或迁移任务。共享的只是仓库导航、许可证和通用 CI 工具。

Skill 默认长截图、可安全执行的局部去水印、完整谱行分页及全部页面查看；恢复规则见 [Skill 阶段指南](agents/stage-recovery-layout.md)，验证见 [Skill 验证](skill-verification.md)。以下模块、状态及事务规则只属于程序与网站。

程序转换通过图像处理保留可见谱面，生成 A4 PDF、全部预览及来源记录。`complete` 只表示产物完整发布；`reliable=false` 明确未经音乐校对。

## 模块与执行边界

| 模块 | 职责 |
| --- | --- |
| `core.py`、`imaging.py` | 输入预算、来源 hash、原生采样、位移配准、保守合成与完整条带分页。 |
| `supervision.py`、`guardian.py` | 独立转换进程、采样资源监督、取消与异常树清理。初始 PID/start-time 固定，后续观察不替换已有身份。 |
| `public_video.py`、`short_links.py`、`anonymous_backend.py`、`bbdown_cli.py`、`bbdown_network.py`、`youtube_backend.py`、`anonymous_network.py` | B站固定 BBDownNext 2.3.0 直连解析，YouTube 固定 yt-dlp 匿名解析；公共 DNS/TLS、重定向与同流备份、完整曲长和实测媒体校验。 |
| `video_seek.py` | 有限时 FFmpeg 解码、实际 PTS/time_base、原生运动摘要和临时帧清理。 |
| `cli.py`、`arguments.py` | JSON 与参数适配；非法输入不反射载荷、路径或原始异常。 |
| `web.py`、`static/` | 同源网页、能力认证、真实阶段及 FD 分块下载。 |
| `schema.py`、`maintenance.py`、`owned_tree.py` | 共享已知 schema、停服快照、完整性核验、新身份恢复及有界私有根清理。 |
| `jobs.py`、`worker.py`、`service_limits.py` | SQLite 队列、排他 worker、发布决定、存储准入、保留期和受管清理。 |

程序与网站模块位于同一 Python 包；wheel 不包含 Skill、实验视频或机器认证。基础依赖与网站可选依赖由 `pyproject.toml` 定义。

## 转换与发布

固定比例纵向滚谱按实际解码顺序采样，记录实际 PTS 和 time_base，不重排尾部回退的 PTS。原生小图运动摘要检查固定周期采样可能漏掉的重复系统；有多个无法区分的位置时返回 `discontinuity`。唯一位置可接续时，背景或播放标记变化不导致整曲误拒。

同一原谱位置去重，后续位置的重复音乐保留。RGB 合成保留无法确认安全移除的记号、水印和底色。分页选用完整谱行或连续行组之间的空隙，统一比例、连续覆盖；超高组整体缩小，不硬切相关记号。每页实际嵌入一个连续原图条带。

监督进程在私有临时根准备 PDF、全部预览和 manifest 后，使用排他原子发布。输出存在则拒绝；来源 hash 在处理前后核对。Linux guardian 只按初始目录 inode 清理本任务临时根。服务锁被 guardian 继承，在实际写入树停止前不释放，避免新 worker 接管仍有旧写入者的任务。

Linux 取消时先以 SIGSTOP 停驻已登记进程，再反复扫描和停驻新增后代，避免最后一次采样后创建的独立下载进程组遗漏。冻结最多等待 1 秒，随后按原始 PID/start-time 核对并终止整个受管组，继续由实际写入者退出检查决定清理时机。不可中断 I/O 可能延迟信号生效。guardian 对自己已观察到的进程使用相同机制；监督进程被强杀、根进程先退出且新独立会话尚未被 guardian 观察到的极短窗口，仍不构成完整后代发现保证。

## 网站事务与数据

HTTP 接受公开 HTTPS BV、b23.tv 或 YouTube 单视频链接，只做本地格式校验和入队。短链接在受监督获取进程中展开至 BV 视频，重计算由独立 worker 调度器执行，`--concurrency` 配置 1 至 8 路，默认 1。每个监督线程调用独立的转换进程及 guardian。SQLite 短 `BEGIN IMMEDIATE` 事务原子检查活动名额与空间预留，部分唯一索引限制每 IP 一个未完成任务；全站最多 10 个等待任务。只读状态与取消轮询不申请写锁，同一调度器内的短事务串行协调，清理或领取轮询的短暂数据库忙不会终止全部活动转换。随机任务 ID 与 256 位能力凭据独立生成；SQLite 只存凭据摘要。IP 限流不代表所有权。

转换排他发布到私有 attempt/result 后，worker 核对 PDF 和全部预览，清理线上原生帧及长图并更新 manifest，再持久保存 `finishing` 决定及完成/到期时间。此后取消不撤销结果。重启核验同一决定，恢复完成而不延长保留期；未作完成决定的活动任务标为 `interrupted`，只允许显式重试。

服务暂存根在启动子进程前登记 ownership marker 与根 device/inode，整服务树终止后只恢复清理身份匹配的确切私有根。未知根、attempt 外文件和替换 marker 保留。备份/恢复在排他发布前 fsync 所有嵌套目录，核验拒绝未知 schema、额外文件、链接与特殊文件。具体命令见[维护指南](script-product/maintenance.md)。

服务 schema 显式使用 SQLite `user_version=4`，拒绝自动打开旧库及未知版本。v1、v2、v3 快照分别通过显式 `upgrade-v1`、`upgrade-v2`、`upgrade-v3` 核验后升级到新目录，见[维护指南](script-product/maintenance.md)。`managed_attempts` 记录 task/attempt、受管根 device/inode，以及生成文件的相对路径、device/inode/ctime。清理从数据根经 no-follow 目录 FD 遍历，只 unlink 身份仍匹配的文件，未知文件和替换物保留。目录只在空时移除。恢复到新目录必须先核验备份清单/hash，再登记工具自己新建的文件身份；数据库旧 inode/ctime 不可直接当作新副本所有权。

`submission_events` 保存成功入队的 IP 摘要和时间，提交、重试、额度检查在同一短写事务中完成。最近十分钟限十次，最近二十四小时限一百次，取消不退次数，不设置全站每日额度。过期计数在成功入队及 worker 清理时删除；重启和同版本备份恢复保留计数。`submission_control` 保存运营者暂停接收新任务的状态，暂停不影响领取既有队列和访问结果。任务身份在原到期时刻后再保留三十天，正常受管清理后删除身份及其受管登记，未知残留文件保持原样。具体契约见[防滥用方案](script-product/abuse-prevention.md)。

到期状态与认证打开文件共用事务序列。到期先拒绝新访问，再物理 unlink，Linux 已打开 FD 可继续读完。worker 每次轮询及启动恢复后执行清理。结果默认 24 小时，失败/取消/中断默认 1 小时；仅存脱敏错误码和信息，错误文字全局限额 8MiB。到期行只保留用于到期响应的任务身份，不保留来源、结果摘要或诊断文字。

入队、重试与领取要求 `used + (active + 1) * max_temp <= retained` 且空闲空间至少 `min_free + (active + 1) * max_temp`。运行时约每 200ms 检查当前逻辑用量和空闲底线。`used` 包含 attempts 中全部普通文件及未知文件，不提前删除有效结果换取名额。采样额度不能代替 cgroup 或文件系统硬限额。

## 安全与范围

YouTube 的匿名范围、客户端回退、IPv4 与代理、响应上限及安装要求见 [YouTube 获取](script-product/youtube.md)。B站依旧直连；YouTube 可继承标准 HTTPS 代理变量，代理认证不转发给源站。

匿名获取不加载用户 Cookie、netrc、下载器配置、插件或模型认证。初始 URL、每次重定向、每个媒体候选均校验公共地址和支持的 HTTPS 域；实际连接固定已核验 IP，同时保持原 TLS 主机名。代理认证不转发到源站；签名 URL 和原始异常不写入产物或公开日志。允许的 API 回退、分 P、完整时长与媒体尺寸检查保留。

程序与网站的支持范围和具体资源参数见[转换契约](script-product/conversion.md)及[网站运行](script-product/website.md)。这些入口不执行模型编排、重绘、轮廓转描、MIDI 或人工批准；Skill 的可选路线只在其独立工作流内执行。历史实验和现有安装保留，不自动迁移任务。
