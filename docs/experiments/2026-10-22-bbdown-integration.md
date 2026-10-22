# BBDownNext 2.3.0 接入与恢复开放

2026-10-22，按用户“用 BBDownNext 2.3.0 替换 yt-dlp，就换入口，保持直连，并从获取阻塞处继续原路线”的要求完成。公开网站为 https://drum.kenqia.top/ 。没有 push、PR、合并 main 或关闭工单。

## 发行和范围

应用提交 `538f758a368cc51df3cc6a5e2eea1ebf67fb5a86`，tree `e5c7873eb9f26f7a6e5aaa1820d04678d48a9cf4`，版本 0.1.1。wheel SHA256 `3cd4e6caec9b64bced0e41ae71df26028758477d4a920fcfa402a9f76cae28e8`。后续 `a0d5d34` 仅补构建依赖文档，25 个应用文件不变。

固定 CLI 仅解析元数据，原 Python 媒体传输、图像整理、分页、队列、期限和备份接口保留。原版调试 view 响应在 8192 字符截断，无法完整绑定来源。因此使用准确 v2.3.0 的 `metadata-bounded.1`，仅调整调试上限与 HTTP 响应读取上限，未改变下载、TLS 或匿名接口逻辑。[补丁与构建来源](../bbdown-build.md)随仓库保留。执行前只接受该构建的固定 SHA256 `d5fe48f6c2bf2e388937d3c8985c1e3dcca678e5a8d8345fa5c31e36793baf0a`，原版启动前拒绝。

每次复制单文件到私有 AppDir，空配置、干净环境，不读取安装位置旁的账号或 Cookie。任务内 CONNECT 中继验证并固定公共数值 IP，TLS 保持端到端校验；它直接连接公网，不是 VPN。媒体传输也强制直连，不改变全局代理、路由或其他应用。

## 验证

证据根目录 `/home/kenqia/issue69-context/bbdown-integration-20261022`。

| 验证 | 实际结果和证据 |
| --- | --- |
| 全回归 | 169 项，116.421 秒，无跳过，`full-regression-final.log` |
| 独立 C# 构建边界 | 12 项通过，完整 82,346 字节 JSON、2 MiB 边界、未知/谎报长度、真实自动 gzip 解压后限额和取消，`bounded-build-validation.md` |
| 安装 | base/web 离线安装、依赖检查、25 文件源码/sdist/wheel/安装一致、均无 yt-dlp，`merger-packaging-report.md` |
| 共同入口 | Python/CLI/HTTP 经过真实合成 CLI 进程，检查成功、来源、构建摘要、拒绝和不发布 |
| 云端完整小星星 | `BV1np421S78S?p=1`，来源 API 63.9 秒，实测 63.756 秒、746×480、1,357,431 字节，SHA256 `062c556fee5e6796cc4abbcc511d2a2611728b363edea9eabaa254e0989f8d86` |
| 目标机网站生命周期 | 排队/运行取消、SIGTERM 中断重试、完整转换、所有页/PDF 哈希、停服 backup/verify/restore、原期限、45 秒实际到期三入口 410 和物理清理，`target-acceptance-final.json` |
| 目标机十页 | 正式安装维护 CLI 的十页顺序/hash 往返和重复/错序/穿越/额外页拒绝，1 项 1.868 秒，`target-tenpage-acceptance.stdout` |
| 隔离浏览器 | 实际云端候选站，关闭后返回、预览、下载、移动端无横向溢出、20 秒后刷新显示到期，`browser/report.json`；受管文件已物理删除 |
| 公网浏览器 | 显式直连的独立 Chromium 正常 CA 校验，201 提交、状态/预览/PDF 均 200，关闭后返回及下载成功，无页面/console 错误，`production-browser-direct/report.json` |

新 PDF 1 页，SHA256 `4fce08ef13cf8c4d9639fcf90fc9ee9588f61226a425dcdd76bcf61d89a3e43f`，Root 实际查看了全页及浏览器结果。没有声称音乐识别或逐符号校对。公网默认保留 86400 秒，隔离缩短测试不改变默认值。

## 生产状态和恢复

`/srv/drum-score/current` 指向上述 538 发行。仅更新鼓谱服务 unit、专属 nginx 站点和当前链接。两个鼓谱服务 active/enabled；web 为 128 MiB/50% CPU，worker 为 512 MiB/100% CPU，swap 禁用。正式 worker 实际完整转换的 cgroup MemoryPeak 初次观测 139,292,672 字节。候选完整转换 153,026,560 字节，应用树 RSS 采样与 cgroup 计量单列，不混用。

切换前正式停服 backup/verify 成功，备份 `/var/backups/drum-score/pre-bbdown-20261022-v2`；配置副本与切换报告位于 `/srv/drum-score/deployment-bbdown-20261022-v2`。旧 ee9 发行和数据保留。回滚先停止两个鼓谱服务，切回旧发行，恢复该目录 `pre-change/` 下本服务 unit 与闭站 nginx 文件，再 daemon-reload、nginx -t/reload 并禁用鼓谱自启。不得删除数据或其他应用。

外部 GET 返回 200，正常 CA 校验结果 0。nginx 主进程 3513266、zju-search 2399447、mihomo 2288981 保持不变；仅 nginx reload。原四个匿名 HTTP 回归仍 401、88 字节、hash `2667565a96113d822f72929eeaf8f24fda510f251b3082f6c6051ac200be5561`。路由 hash `e7e27d947a7a81276ae01a5f3719a11c631e38c3a4fbb67f73b570fc4b7acf91`、策略规则 hash `c88a415e55c2b1d6ac4dd37c5ec360cbf3f5880a44aa1ecf71598f1d3ce4cbe2` 与切换前相同。临时 8792/8793/17890 服务端口及本机 48866 隧道均已结束。

## 失败及修正

- 首轮全回归的比较 fixture 缺 `__init__.py`，误导入 editable 安装包；只补 fixture。第二轮 PID 复用测试的两个独立观察者共用 marker，导致首次观察身份竞争；改双观察者屏障并串行 20 次验证，生产监督代码不变。
- 原 CLI 截断来源、view/player 同字段误判都先拒绝，修复后通过；未放宽身份或完整性判断。审阅要求拒绝原版 64 MiB 解压预算，已修复，两轴未决均为 0。
- RuntimeDirectory 的任务子目录 noexec 导致临时 CLI 启动被拒绝；StateDirectory 完整转换通过，正式 unit 原本即使用 StateDirectory。
- 首个归档含 wheelhouse 符号链接，解包前拒绝；改按 manifest 写普通文件并重新传输核验。安装脚本遗漏 `/usr/sbin` 时已完成 venv 安装但尚未通过服务用户 help；改绝对 runuser 路径后逐文件复验，无共享 Python 变更。
- 首个恢复验收控制进程提前结束，改独立有界 systemd 控制进程并保存进度。恢复 API 到期通过后，脚本漏启动恢复 worker，文件尚未清理；补启动正常 worker，3 个登记文件物理删除。最终报告明确 `passed_after_harness_resume`，不隐藏原失败。
- 浏览器完成页不自动轮询到期，原测试等自动变化超时；按现有行为等待后刷新，实际到期提示通过。首次公网浏览器受请求路径不稳定影响，显式禁用代理后全流程通过，没有修改网站来迎合测试。
- 首次生产切换在服务就绪前立刻检查端口，连接拒绝，自动恢复旧发行与闭站配置。增加 10 秒有界就绪等待后重切成功。两次备份和失败报告均保留。

这些结果只证明指定来源及上述边界。本轮未运行全部上游 C# 测试、没有验证任意 B站视频都可匿名获取，也没有修改既有本地预览环境或旧桌面交付包。
