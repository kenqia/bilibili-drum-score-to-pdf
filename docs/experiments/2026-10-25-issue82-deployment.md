# Issue #82 推送、工单关闭与部署

2026-10-25，用户明确指示“push，关闭工单，然后部署”。已推送 `codex/issue82-integration` 的 `bb2f2e3da3b7dc3ff6e993183c20634e0fd88030`，关闭 #82–#86，并部署到 <https://drum.kenqia.top/>。未创建PR或合并main，原工作区及并行员工的在线人数、临时PDF调整均保留。

## 推送和关闭范围

GitHub直连及默认代理环境多次EOF。核对现有 `NO_PROXY` 含GitHub域名后，仅为本次命令覆盖该列表，使用现有SSH通道和临时SOCKS转发完成API访问，没有修改认证、SSH或全局代理配置。Git经 `ssh.github.com:443` 和已有本机HTTP代理推送到独立集成分支，未强推。

关闭评论明确说明：代码与工程检查已交付，但十三个原失败来源仅一个恢复，十二个仍受控失败；真实多面板自动选区与固定覆盖物改善仍缺同类前后证据。关闭是本轮明确指示的工单处置，不代表未验证项已经通过。完整本地验收见[交付记录](2026-10-25-issue82-delivery.md)。

## 发行与目标机预检

发行目录为 `/srv/drum-score/releases/issue82-fcd55f8a810bbc35`。准确wheel SHA256：

```text
fcd55f8a810bbc3549bd4af1329ba3f88d7a51c8152f161c64023cecf32abed4
```

在新venv使用现有wheelhouse离线安装，pip check通过。全部40个包文件与wheel和本地最终源码字节一致。复用已核验BBDownNext2.3.0二进制，未重新引入yt-dlp/EJS或Deno，不升级系统依赖与旧环境。

隔离预检根为 `/var/lib/drum-score-restore/issue82-preflight-20261025-3`。HTTP在原128MiB、50%CPU限制与同类沙箱下完成四页/一页临时排版；worker在原1GiB、150%CPU、八路配置下执行同一真实来源两次 `[0,29)` 选段，全部PDF/预览hash、选项、来源hash通过。两次均 `bypass_version`，说明目标机出口未取得足够的媒体版本证据；正常获取和转换继续，不能声称目标机真实缓存命中通过。本地真实fill→hit证据不能替代这个结果。

最终预检web峰值92405760字节，worker峰值168964096字节，均无high/max/OOM事件。试验服务全部停止。

初次脚本把合法201入队响应误判为失败；第二次要求真实来源必须hit而实际安全旁路。两次均为验收脚本假设问题，报告保留，修正判据后才记录最终预检通过，没有放宽来源版本或缓存保护。

## 显式升级与切换

北京时间15:33:39暂停新提交并排空队列，停止web和worker。停服时原库302条任务。旧发行创建并核验v3快照：

```text
/var/backups/drum-score/before-issue82-v3-20261025-073338
```

新发行执行 `upgrade-v3` 到不存在的新目录 `/var/lib/drum-score-restore/issue82-v4-20261025`。升级后原302条任务的ID、完成和到期时刻逐项一致，旧根保持原样，仅维护窗口暂停标记发生显式变化；新任务参数为兼容默认值，缓存表初始为空。新v4根再创建备份并verify：

```text
/var/backups/drum-score/issue82-v4-20261025-073338
```

保留两份原profile后，只将本服务的WorkingDirectory、ReadWritePaths和命令数据根改为新v4根，显式加入 `--cache-mib 1024 --cache-retention-seconds 86400`。原子切换current，核验启动后恢复原接收状态。15:33:50服务开放。保留原八路worker、1GiB上限、150%CPU和原存储/期限保护。DNS、TLS、nginx和另一应用没有修改。

## 公网验收

实际Chromium通过公网提交完整 `BV1fbFczHE1r?p=1`，最终复测86.190秒完成，来源hash为 `abbb40222ce2c3db0ae9b390f2a9dcd1e492182c292d23ba875e1b437df1cc93`。默认两页A4，所有页面API hash和浏览器预览通过。A5、每页目标两行生成十三页，全部预览、实际下载、刷新恢复默认、原PDF及期限不变通过。默认PDF SHA256为 `59a152edb11562f9894da0b9633126815b2ec2c21cf57979d2d126c19e4fc3af`。

高级选项默认折叠、反向时间不POST、无来源视频播放器、390px无横溢出且无pageerror。Root实际查看默认两页、手机十三页全图及局部截图，标题、署名、段标、后续重复和123末行终止线可见，非逐音符音乐校对，`reliable=false`。

首次浏览器脚本以空预览列表的 `every()` 提前通过等待条件，默认页数误记为零。该报告已标为无效并保留，复跑增加精确预期页数与每张图解码检查，得到上面的两页/十三页结果。

WSL和服务器初轮HTTPS探针分别20/20为200，最慢0.746秒和0.068秒。不能把上线验收当八路生产压力测试。

## 后续OOM与内存调整

22:01系统记录web的 `CONSTRAINT_MEMCG` OOM，systemd自动重启一次。具体触发请求未知，没有读取用户请求或认证日志。初轮检查时未发生此事件，后续不能再称“上线后无OOM”。worker没有自动重启，nginx和另一应用保持active。

当时web使用原96MiB软水位/128MiB硬上限。确认机器可用内存约1.4GB后，在本次部署范围内将web软水位改为192MiB、硬上限改为256MiB；worker仍为1GiB，合计上限1.25GiB。保留新v4原profile副本，原子修改本服务profile并用runtime属性即时应用，无需重启。未扩大CPU、Swap或worker预算。

原web配置副本为新发行的 `rollback/web-v4-before-memory-adjustment.conf`。该变更解决限额余量问题，不等于已经定位或修复具体请求的内存根因。调整后公网完整转换84.936秒通过，默认两页、临时A5十三页、全部预览/下载、刷新与原hash/期限不变再次通过，默认PDF字节与调整前相同。该次来源获得充分版本证据，成功fill且缓存期限为86400秒；未再提交第二任务验证hit，不把fill写成hit。HTTPS探针20/20通过，最慢0.106秒。随后NRestarts仍为1，没有新增重启；这段有限验收不能证明未知请求不会再触发内存压力。证据见 `browser-memory-adjusted/`、`health-after-adjustment.json` 与最终资源报告。

## 证据和回滚

本地留证目录为 `work/engineering/2026-10-25-issue82-deploy/`，包含安装身份、三个预检及失败、升级回执、工单关闭回执、公网浏览器报告/截图/PDF、健康探针、OOM核对、内存调整和最终状态。测试能力凭据只在进程内持有，截图遮蔽能力字段，没有记录用户已有凭据或原始敏感日志。

旧发行 `/srv/drum-score/releases/withdraw-ce0dd1317da6846d`、旧v3根 `/var/lib/drum-score-restore/abuse-v3-20261024`、已核验v3/v4备份和新发行 `rollback/` 保留。切换后已产生新的v4任务，不可直接覆盖或让旧程序打开v4。

若回滚代码及schema，先暂停新提交，排空并停本服务，保存新v4数据；恢复旧profile和current至旧发行/旧v3根，并将web运行时内存属性恢复至匹配旧预算，再启动。原v3根仍保留维护暂停标记，应按原接收状态显式恢复。新v4任务不会回灌旧库，须保留，不自动删除或合库。若只撤回内存调整，先确认当前占用可安全缩小，保存停服状态后恢复v4原profile及对应runtime属性。此次没有执行数据回滚。
