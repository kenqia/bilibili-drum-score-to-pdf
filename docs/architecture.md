# 鼓谱转换架构

Python、CLI 和匿名网站共用 `drum_score.convert`。转换通过图像处理保留可见谱面，生成 A4 PDF、全部预览及来源记录。`complete` 只表示产物完整发布；`reliable=false` 明确未经音乐校对。当前决定见 [ADR 0006](adr/0006-script-product-lifecycle.md)。

## 模块与执行边界

| 模块 | 职责 |
| --- | --- |
| `core.py`、`imaging.py` | 输入预算、来源 hash、原生采样、位移配准、保守合成与完整条带分页。 |
| `supervision.py`、`guardian.py` | 独立转换进程、采样资源监督、取消与异常树清理。初始 PID/start-time 固定，后续观察不替换已有身份。 |
| `public_video.py`、`anonymous_backend.py`、`bbdown_cli.py`、`bbdown_network.py`、`anonymous_network.py` | 固定 BBDownNext 2.3.0 匿名解析与直连获取，公共 DNS/TLS、重定向与同流备份、完整曲长和实测媒体校验。 |
| `video_seek.py` | 有限时 FFmpeg 解码、实际 PTS/time_base、原生运动摘要和临时帧清理。 |
| `cli.py`、`arguments.py` | JSON 与参数适配；非法输入不反射载荷、路径或原始异常。 |
| `web.py`、`static/` | 同源网页、能力认证、真实阶段及 FD 分块下载。 |
| `schema.py`、`maintenance.py`、`owned_tree.py` | 共享已知 schema、停服快照、完整性核验、新身份恢复及有界私有根清理。 |
| `jobs.py`、`worker.py`、`service_limits.py` | SQLite 队列、排他 worker、发布决定、存储准入、保留期和受管清理。 |

所有生产模块位于同一 Python 包；wheel 不包含旧 Skill、实验视频或机器认证。基础依赖与网站可选依赖由 `pyproject.toml` 定义。

## 转换与发布

固定比例纵向滚谱按实际解码顺序采样，记录实际 PTS 和 time_base，不重排尾部回退的 PTS。原生小图运动摘要检查固定周期采样可能漏掉的重复系统；有多个无法区分的位置时返回 `discontinuity`。唯一位置可接续时，背景或播放标记变化不导致整曲误拒。

同一原谱位置去重，后续位置的重复音乐保留。RGB 合成保留无法确认安全移除的记号、水印和底色。分页选用完整谱行或连续行组之间的空隙，统一比例、连续覆盖；超高组整体缩小，不硬切相关记号。每页实际嵌入一个连续原图条带。

监督进程在私有临时根准备 PDF、全部预览和 manifest 后，使用排他原子发布。输出存在则拒绝；来源 hash 在处理前后核对。Linux guardian 只按初始目录 inode 清理本任务临时根。服务锁被 guardian 继承，在实际写入树停止前不释放，避免新 worker 接管仍有旧写入者的任务。

## 网站事务与数据

HTTP 只提交公开 BV 链接，重计算由独立串行 worker 执行。SQLite 短 `BEGIN IMMEDIATE` 事务和部分唯一索引限制每 IP 一个未完成任务、全站 10 个等待加 1 个活动任务。随机任务 ID 与 256 位能力凭据独立生成；SQLite 只存凭据摘要。IP 限流不代表所有权。

转换排他发布到私有 attempt/result 后，worker 核对 PDF 和全部预览，清理线上原生帧及长图并更新 manifest，再持久保存 `finishing` 决定及完成/到期时间。此后取消不撤销结果。重启核验同一决定，恢复完成而不延长保留期；未作完成决定的活动任务标为 `interrupted`，只允许显式重试。

服务暂存根在启动子进程前登记 ownership marker 与根 device/inode，整服务树终止后只恢复清理身份匹配的确切私有根。未知根、attempt 外文件和替换 marker 保留。备份/恢复在排他发布前 fsync 所有嵌套目录，核验拒绝未知 schema、额外文件、链接与特殊文件。具体命令见[维护指南](script-product/maintenance.md)。

服务 schema 显式使用 SQLite `user_version=1`，拒绝旧未版本化库及未知版本。`managed_attempts` 记录 task/attempt、受管根 device/inode，以及生成文件的相对路径、device/inode/ctime。清理从数据根经 no-follow 目录 FD 遍历，只 unlink 身份仍匹配的文件，未知文件和替换物保留。目录只在空时移除。恢复到新目录必须先核验备份清单/hash，再登记工具自己新建的文件身份；数据库旧 inode/ctime 不可直接当作新副本所有权。

到期状态与认证打开文件共用事务序列。到期先拒绝新访问，再物理 unlink，Linux 已打开 FD 可继续读完。worker 每次轮询及启动恢复后执行清理。结果默认 24 小时，失败/取消/中断默认 1 小时；仅存脱敏错误码和信息，错误文字全局限额 8MiB。到期行只保留用于到期响应的任务身份，不保留来源、结果摘要或诊断文字。

入队、重试与领取要求 `used + max_temp <= retained` 且空闲空间至少 `min_free + max_temp`。运行时约每 200ms 检查当前逻辑用量和空闲底线。`used` 包含 attempts 中全部普通文件及未知文件，不提前删除有效结果换取名额。采样额度不能代替 cgroup 或文件系统硬限额。

## 安全与范围

匿名获取不加载用户 Cookie、netrc、下载器配置、插件或模型认证。初始 URL、每次重定向、每个媒体候选均校验公共地址和支持的 HTTPS 域；实际连接固定已核验 IP，同时保持原 TLS 主机名。代理认证不转发到源站；签名 URL 和原始异常不写入产物或公开日志。允许的 API 回退、分 P、完整时长与媒体尺寸检查保留。

支持范围和具体资源参数见[转换契约](script-product/conversion.md)及[网站运行](script-product/website.md)。旧模型编排、重绘、轮廓转描、MIDI 和人工批准入口已退役；历史代码、实验和既有 Skill 安装分别保留，不自动迁移。
