# 在线人数与打印排版部署

2026-10-25，用户明确要求“推送并且部署”。已将应用提交 `f98d3576c679a0889c0a4e39d788514c5ad3cca2` 推送到 `origin/codex/parallel-conversions`，并部署到 `https://drum.kenqia.top/`。没有创建 PR 或合并 main，没有修改 DNS、TLS、nginx、其他应用或正式资源预算。

## 发行与安装

新发行目录为 `/srv/drum-score/releases/print-c4115c64ed7858aa`。wheel SHA256 为 `c4115c64ed7858aa2376753aae1cf2cc70def2279bf543449dc57dc4a9cfeaf6`，33 个安装包文件逐字节核验，`pip check` 通过。本地 230 项回归、浏览器验证及两份独立安装见[实现验证](2026-10-25-print-layout.md)。本轮没有修改应用源码，不重复全量回归。

旧线上发行尚不包含上轮本地 YouTube 接入。新发行沿用旧 wheelhouse，另在本轮发行目录安装准确的 `yt-dlp==2026.10.21`、`yt-dlp-ejs==0.8.0` 和 Deno 2.9.8，不改系统 Python、旧环境或全局代理。BBDownNext 二进制仍为原核验版本。Poppler `pdfimages` 已存在，无需安装系统包。

GitHub 普通 SSH 连接停滞，最终通过现有本机 HTTP 代理连接 `ssh.github.com:443` 推送成功，没有写 SSH 或代理配置。Deno 使用官方 GitHub Release API 下载资产，压缩包与 API 给出的 SHA256 `e890975bc2549807bbcc0b584ffafda72cc7c93349dd99c80483dd784f6c4609` 一致；解压可执行文件 SHA256 为 `368bca08999e02c6911b8f248167b582276b1f547db5712b6e736d7eda1dbda7`，与本地既有试验记录一致。

## 预检与切换

初次预检把测试驱动、web 和排版进程一起放进 128 MiB cgroup，请求超过测试脚本的三十秒期限。该结果未用于宣称服务通过，也未影响正式服务。随后将驱动放在 cgroup 外，在正式 web 相同的 MemoryHigh 96 MiB、MemoryMax 128 MiB、Swap 0、CPUQuota 50%、TasksMax 64、FD 512 和文件系统沙箱下单独运行服务。

隔离 HTTP 复测四页与一页排版分别耗时 1.536、1.117 秒，cgroup 内存峰值 89575424 字节，high/max/oom/oom_kill 均为零。全部 PDF/PNG 完整、原任务与期限不变、受管临时目录清理通过。实验使用独立根 `/var/lib/drum-score-restore/print-preflight-20261025`，不接触用户任务。

北京时间 10:55:23 停止 web 接收，排空 worker 后停止 worker。使用匹配旧发行创建并核验完整备份：

`/var/backups/drum-score/backup-before-print-20261025-025523`

原数据根 `/var/lib/drum-score-restore/abuse-v3-20261024` 和 schema 3 保持不变，不迁移或重置任务。原子切换 `current` 后启动 web，核对原 271 条记录的 `completed_at`、`expires_at` 完全一致，再启动 worker。10:55:31 两个正式服务均已运行。旧发行 `/srv/drum-score/releases/abuse-18534ac519e22e03`、备份及两份 profile 副本保留。

## 公网验收

WSL 上的实际 Chromium 通过公网 HTTPS 提交真实 B站来源 `BV1rH4y1R7Rk?p=1`，约 62.389 秒完成。谱面可见标题为《可惜没如果（新版）》，本轮没有逐符号音乐校对。

| 检查 | 结果 |
| --- | --- |
| 首页在线人数 | 显示近似在线人数 |
| 默认 PDF 和全部预览 | 两页，完成加载 |
| A5、每页目标两行 | 六页，所有预览与临时 PDF 同步切换，实际下载通过 |
| 刷新 | 恢复默认参数和两页默认结果 |
| 默认产物与期限 | 重排前后 PDF 字节及到期时刻相同 |
| 手机布局 | 390 像素视口无横向溢出 |
| 浏览器异常 | 无 pageerror |
| 后续 HTTPS 探针 | 20/20 为 200，最慢 0.132 秒 |

默认 PDF SHA256 为 `703987c7155e4122101b77cf0f8d87b5b591e7e0657de543a95a750f56029a0f`。实际查看了公网临时六页预览截图；每页两行的偏好会增加留白，不把该偏好当作默认紧凑布局效果。非纯白背景、连接边框与不可拆分组的留白限制继续保留。

正式 web 内存峰值 100827136 字节，MemoryHigh 事件两次，max/oom/oom_kill 均为零。worker 内存峰值 263561216 字节，high/max/oom/oom_kill 均为零。两服务自动重启均为零，nginx 与 zju-search 保持 active；磁盘可用约 9.48 GB。该结果只证明本轮单份真实转换与排版，不替代八路压力测试。

另通过正式 HTTP 提交真实 YouTube 来源 `https://youtu.be/9RwL9af9-Do`，42.110 秒后受控失败，错误码 `public_api_unavailable`。固定依赖与 Deno 已安装，但目标机 YouTube 获取尚未通过，不能宣称已可用；本轮没有调整服务器出口或导入认证。

## 证据与回滚

本地证据位于 `work/engineering/2026-10-25-print-deploy/`，包括 prepare/preflight/deploy 脚本及日志、`deployment.json`、`preflight.json`、`public-browser-report.json`、桌面及手机截图、实际临时 PDF、`public-health.json` 和 `final-state.json`。截图遮蔽本轮任务能力链接；未读取或记录用户已有任务凭据。试验脚本只在进程内持有自己创建的验收任务凭据。

服务器新发行保留 `installation.json`、`deployment.json`、`final-state.json` 和 `rollback/`。临时 systemd 预检服务已停止，正式服务保持原八路 worker 与资源参数。

若需回滚，先停止本服务 web 并排空 worker，再停 worker，将 `current` 原子切回保留旧发行并启动两个 unit。同一 schema 和数据根保留新入队任务，无需恢复旧快照覆盖当前数据。旧发行不支持 YouTube，新加入的 YouTube 任务应先排空或明确处理；本轮收尾已无 queued/running 任务。若需恢复数据，使用已验证备份和现有维护流程，不覆盖运行目录或延长期限。本轮未触发回滚。
