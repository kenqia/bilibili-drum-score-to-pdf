# 服务器部署与待开放状态

2026-10-22，用户明确确认部署后，已将应用安装到 `118.25.26.140`，配置独立域名 `drum.kenqia.top`。服务器匿名获取 B站来源失败，用户随后选择“先保留已部署待开放状态”。公网 HTTPS 返回 503 待开放页面，鼓谱两个服务均已停止并禁用自启。当前不能声明 #69/#74 公网转换验收完成。

## 安装身份与范围

应用发布提交为 `ee9a32010a6ff4966d6d5aa6ed09eef8a34f1e3a`，wheel SHA256 为 `428771b64b42447ae12225bdceb5ad9ee41de84e341a0aef59e2de402f9d1dd4`。本记录之后的文档提交不改变服务器应用版本。

目标系统为 Ubuntu 24.04、Python 3.12.3、systemd 255。离线安装应用和固定依赖后，依赖检查、23 个安装文件身份及四个 CLI 帮助入口通过。仅新增 Poppler 相关三个包和 `python3-pip-whl`，未升级共享 Python。独立虚拟环境通过发行版 pip wheel 引导。

新增对象及保留位置如下。

| 对象 | 位置或状态 |
| --- | --- |
| 专用用户 | `drum-score`，无登录 shell |
| 不可变应用版本 | `/srv/drum-score/releases/ee9a32010a6ff4966d6d5aa6ed09eef8a34f1e3a` |
| 当前版本链接 | `/srv/drum-score/current` |
| 数据根 | `/var/lib/drum-score` |
| systemd units | `/etc/systemd/system/drum-score-web.service`、`drum-score-worker.service` |
| nginx 独立站点 | `/etc/nginx/sites-available/drum-score`，由 `sites-enabled/zz-drum-score` 引用 |
| 本服务操作记录及配置恢复副本 | `/srv/drum-score/deployment-20261022` |
| 停服备份 | `/var/backups/drum-score/pre-open-20261022` |
| 新根恢复核验 | `/var/lib/drum-score-restore/pre-open-20261022` |

## 已执行验证

- 用户添加 DNS 后，两台权威服务器均返回 A `118.25.26.140`、TTL 600。
- 独立 Let's Encrypt 证书签发成功，SAN 仅为 `drum.kenqia.top`，到期时间为 2027-01-20 02:21:15 UTC。外部客户端使用正常 CA 校验访问 HTTPS，校验结果为 0，页面为预期 503；HTTP 返回 308 转向 HTTPS。
- 本证书保存条件式 nginx 重载 hook。Certbot staging 续期演练及 hook 执行成功，既有续期 timer 保持运行。未复制私钥或认证材料。
- 实际两个 unit 启动成功，web/worker 的 MemoryMax 分别为 128/512 MiB，CPU 配额分别为 50%/100%。独立 64 MiB 临时 cgroup 的内存探针实际触发 `oom-kill`，随后已停止并清理探针状态。这不证明完整视频转换能在生产额度内完成。
- 既有 API HTTPS、staging、默认 HTTP 和后端入口的匿名响应均保持 401、88 字节及相同 SHA256。只验证了匿名入口响应，未进行认证业务回归。nginx、zju-search、mihomo 保持原 PID 运行。
- 停服后，正式维护 CLI 的 backup、verify、restore 均成功，schema 1、备份格式 1、1 个文件、28672 字节。快照只含一次匿名获取失败的数据库，没有完成的鼓谱页面，不能视为目标机多页产物恢复验收。
- 最后复查两个鼓谱 unit 为 `inactive/dead`、`disabled`、MainPID 0，8791 没有监听。仅关闭本次部署的 SSH 转发，本地用户预览和数据继续保留。

## 匿名获取阻塞与剩余验收

后续按用户要求完成[四种下载器的隔离实测](2026-10-22-downloader-comparison.md)：BBDownNext 2.3.0、bilix 0.18.9 在服务器直连下载同一个小星星视频成功，两份文件通过整段解码。Bili23 和恢复 TLS 校验的 lux 在直连及魔戒代理下仍遇到 412。候选工具尚未接入现有 worker，以下原程序失败事实继续保留，生产仍待开放。

用户随后要求按顺序诊断，最新的静默重试、请求代码、代理 CONNECT 与 Windows 隔离浏览器对照见[网络诊断记录](2026-10-22-network-diagnosis.md)。本轮诊断没有改变待开放状态。

用户提供本机FlClash端口后，又完成[VPN隔离测试](2026-10-22-vpn-isolation.md)。中立目标出口确实改变，单次代理获取仍412；用户确认全局模式且B站连接策略为魔戒节点。生产配置与全局路由不变。

通过真实 systemd web/worker 提交公开小星星 `BV1np421S78S`，任务从 queued 转为 failed，返回脱敏错误 `http_unavailable`。服务器直连及既有匿名本机代理均收到 B站网页和元数据接口 HTTP 412。公开回退未能满足现有来源绑定和完整性要求，因此未放宽获取校验，也未开放业务代理。

失败路径的 worker 峰值约 78 MiB，不包含完整下载与解码，不能当作完整转换资源结果。本地同源转换和真实浏览器结果继续有效，不能替代目标机验证。

用户要求保留待开放状态后，已停止网络出口尝试。继续前需用户明确要求恢复，并具备可用的匿名来源访问方式。届时先核对现有安装、DNS、证书、可用资源和备份，再在受控入口验证真实完整转换、全部预览与下载、取消、重启恢复、到期清理和公网反向代理流程。全部通过后才切换业务入口。恢复步骤参考[部署指南](../script-product/deployment.md)，不要直接套用首次安装命令覆盖现有对象。

## 证据位置

脱敏脚本和原始结果位于本次工作环境的 `/home/kenqia/issue69-context/deploy-live-20261022/`。关键记录为 `install-release.stdout`、`install-services.stdout`、`memory-probe.stdout`、`issue-certificate.stdout`、`renewal-dry-run.stdout`、`real-conversion.stdout`、`network-probe.stdout`、`closed-tls.stdout`、`park-deployment.stdout` 和 `final-state.stdout`。这些文件不包含服务器私钥、认证材料或任务能力凭据。
