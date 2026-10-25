# 撤回 YouTube 接入

2026-10-25，用户要求撤回 YouTube 接入的推送与部署。本轮以 `93a234da701710d6d4df50219e57d0bf6d3fba26` 为基线，用新增提交撤销 `b6b8220` 的功能，不改写远端历史。在线人数、默认紧凑排版、临时 PDF 排版及 B站入口保留，独立 Skill 不变。

## 撤回范围

移除程序、CLI、网页对 YouTube watch、youtu.be、Shorts 的接受与获取能力，以及专属后端、yt-dlp 和 EJS 产品依赖。新发行不安装 Deno。旧发行和试验文档保留为历史证据，不删除用户任务或刷新期限。

仅为历史备份恢复保留规范 YouTube 来源的只读校验，提交入口不调用该校验。历史失败任务不再显示重试按钮，服务端也在计入提交额度之前拒绝其重试。历史来源显示为“历史 YouTube 任务（接入已撤回）”。

## 本地与目标机预检

使用现有 Python 3.12.12 环境，在仓库根运行：

```sh
PATH="$PWD/work/engineering/2026-10-23-parallel/venv312/bin:$PATH" python -m unittest discover -s tests -v
node --check src/drum_score/static/app.js
ruff check --select E701,E702 src/drum_score
git diff HEAD --check
```

222 项全量回归通过，耗时 169.009 秒；Python 编译、JavaScript 语法和现有 Ruff 检查通过。未配置静态类型检查器，不声称类型检查通过。新增共同契约验证三类 YouTube 链接在 Python、CLI、HTTP 均先于获取被拒绝，不创建输出。新增维护测试验证历史 YouTube 失败任务备份、verify、恢复及期限不变，并拒绝新提交和历史重试。退役测试及适用断言去向见[测试迁移记录](../test-migration.md)。

首次拒绝测试误用了非 IP 的 TestClient 默认 peer，得到 `invalid_peer`，改用合成 IP 后才作为有效拒绝证据。首次历史兼容测试发现重试会重新入队，已在服务端明确拒绝。失败日志均保留。

双轴静态审阅 Standards 无发现，Spec 指出历史来源被误标为 B站且重试按钮仍显示，已修复并复核。静态审阅不代替测试。全量运行期间仅有该静态页面展示修复，后续 JavaScript 语法检查和重新构建通过。

新 wheel SHA256 为 `ce0dd1317da6846dec51a765897e4feba710a70bfceec1a4b4ec1037fd78e362`。目标机独立发行 `/srv/drum-score/releases/withdraw-ce0dd1317da6846d` 核对 32 个包文件与 wheel 一致、依赖检查通过，确认不存在 yt-dlp、EJS 和 Deno。未更改全局环境或旧发行。

隔离根 `/var/lib/drum-score-restore/withdraw-preflight-20261025` 在正式 web 相同的 128 MiB、50% CPU 和沙箱约束下完成 HTTP 排版：四页与一页分别用时 1.511、1.021 秒，内存峰值 87756800 字节，high/max/oom/oom_kill 均为零，默认结果与期限保持不变。

## 部署证据

撤回与历史任务保护分别提交为 `54e00e4`、`49451892d953b71bb60023e2b8a09af74b92272c`，均已推送到 `origin/codex/parallel-conversions`。最终 wheel 与后一个提交的应用文件一致。前一中间提交未部署。

北京时间 11:31:51 停止 web，确认 worker 排空后停止 worker，用旧发行创建备份 `/var/backups/drum-score/backup-before-withdraw-20261025-033150`。旧、新两份维护入口分别核验该备份，确认历史 YouTube 记录不会破坏后续备份。保留 schema 3 和原数据根 `/var/lib/drum-score-restore/abuse-v3-20261024`，原 279 条记录完成与到期时刻完全一致。原子切换 current 后，11:31:56 两服务均正常启动；没有修改 unit、资源预算、DNS、TLS、nginx 或其他服务。

公网实际 Chromium 验证首页无 YouTube 文案，粘贴 YouTube 链接在网页被拒绝，三类 YouTube 链接直接请求 HTTP 均为 422 `invalid_bilibili_url`。同一浏览器随后提交真实 B站 `BV1rH4y1R7Rk?p=1`，52.136 秒完成。默认两页调整为 A5、每页目标两行后生成六页，全部预览、实际下载、刷新恢复默认、原 PDF 字节及期限不变、手机无溢出、无 pageerror 均通过。此为真实获取与产品交互验收，没有新的逐符号音乐校对。

后续独立 HTTPS 探针 20/20 为 200，最慢 0.200 秒。正式 web 内存峰值 100806656 字节，MemoryHigh 五次、max/oom/oom_kill 均为零；worker 峰值 211267584 字节，内存事件均为零。两个服务无自动重启，nginx、zju-search 保持 active。离线合成重放通过且 PDF 字节相等，不作为真实音乐证据。

旧发行 `/srv/drum-score/releases/print-c4115c64ed7858aa`、原数据、核验备份及新发行 `rollback/` 中的旧 current/profile 均保留，未触发回滚。临时预检服务已停止。若新版本出现故障，可停 web、排空并停 worker，将 current 原子切回旧发行，保留同一数据根；这会恢复 YouTube 入口，应仅在明确需要回滚时执行。不得用旧备份覆盖新任务或刷新其期限。

本地证据为 `work/engineering/2026-10-25-youtube-withdraw/`，包含 regression/rejection/archive 及失败日志、最终构建、离线 replay、prepare/preflight/deploy 脚本与结果、`deployment.json`、公网浏览器报告、截图和临时 PDF。截图遮蔽本轮能力链接，测试凭据只在进程内持有。未知文件、其他线程实验和用户任务原样保留。
