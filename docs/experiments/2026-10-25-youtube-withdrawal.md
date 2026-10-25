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

本地证据为 `work/engineering/2026-10-25-youtube-withdraw/`。部署结果、保留材料及公网验收将在实际执行后补入本节。未知文件、其他线程实验和用户任务原样保留。
