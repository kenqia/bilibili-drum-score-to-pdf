# Issue #86 集成验证

本轮验证 #83 高级选项、#84 画面预检与有界补帧、#85 原视频缓存，以及同期已合入的在线人数、默认紧凑分页和临时打印排版。应用基线为 `f0131af`，实验不修改正式服务、不推送、不部署、不迁移线上 schema。Skill 的源码和依赖未修改，也未运行独立 Skill 回归。

## 公开入口组合

新增 `tests/test_public_contracts.py` 的 `test_cached_selected_result_keeps_presence_print_and_retry_contracts`。测试使用真实 worker 与可解码合成媒体，仅替换外部元数据和传输边界。先完成默认任务，再提交带选段、手动区域和关闭固定覆盖物选项的任务，取消并重试，核对选项保持、缓存命中和无额外媒体获取。随后核对 PDF hash、临时 A3 排版、默认结果和期限不变，以及在线人数保持。

该用例首次执行即通过，耗时 5.014 秒。它验证已有能力的组合，没有编造产品红灯。精确日志在 `/tmp/drum-issue82-context/86/combined-first.log`。

## 验证身份与证据

本轮命令使用 Python 3.12 独立环境 `/tmp/drum-issue82-env`，并将其 `bin` 放在 `PATH` 首位。外部证据根为 `/tmp/drum-issue82-context/86/`。容量和独立安装脚本保留在该目录，不把合成传输当作真实网络测量。实际命令与最终结果在后续段落中记录。
## 真实来源与看图范围

最终应用基线为 `f0131afc0eca074deadee8118d76cb8162660700`，包含独立并行完成的在线人数、紧凑默认分页、临时打印排版和 YouTube 撤回。#86 不恢复 YouTube 依赖或入口。

十三个原失败来源中，一个开发来源恢复，另外十二个仍受控失败。`BV1fbFczHE1r` 的窄重叠纵向视口跳动恢复完整 245.3 秒、22 行、两页。横移来源仍为 `discontinuity`，暗底来源仍为 `unsupported_layout`，其余十例仍为 `discontinuity`。没有对其余十例逐帧定位原因。全部输入 hash 保持；失败时未发布部分产物。失败内部阶段成本和区间未知，记录为 `null`，不把外部墙钟或 RSS 采样当作内部阶段成本。

未参与调参的 `BV1Yw4m1Y7YH`《鲜花》在旧版和最终版均为 27 行、三页。全部实际 PTS、time_base、采样图像 hash、placements、region 和长图 hash 与冻结基线相同。紧凑分页改变了页边界，因此没有要求 PDF hash 相同。Root 实际查看恢复来源全部两页与保留来源全部三页，核对标题、署名、段标、后续重复音乐、小节号、完整末行及终止线。此为工程看图，不是逐音符校对，结果仍为 `reliable=false`。

真实恢复来源没有生成固定覆盖物遮罩。固定 Logo、暂停、翻页和周期歧义能力由合成用例验证，不能据此声称真实遮罩修复已验收。

完整来源表与限制见外部留证目录 `/tmp/drum-issue82-context/root-real-source-report.md`；逐项重放见 `after-f0131af/summary.json`、`development-after-f0131af/summary.json`，全部最终页面看图记录见 `root-final-visual-review.json`。亲测 PDF 和所有预览保留在 integration 工作区 `work/engineering/2026-10-25-issue82/deliverables-f0131af/`，不把真实媒体放入 Git。

## 真实缓存与浏览器边界

真实 B站来源的两次 worker 转换为 `fill → hit`，实际媒体打开数保持 1，Range 预检由 1 增至 2；缓存发布和到期时刻不变，TTL 为 86400 秒。两次都选择 `[0,29)`，共 59 个实际采样，最后采样为 28.967 秒、PTS 463472、time_base 1/16000。PDF 和唯一预览 hash 相同。缓存实施者实际查看该页，这不属于完整曲目或音乐校对。证据见 `/tmp/drum-issue82-context/85-real-cache/evidence.json`。

最终 Chromium 检查覆盖高级选项和 heartbeat，手机页面已实际查看，确认默认折叠、反向时间拒绝、手动区域、实际提交选项、无横溢出或 pageerror。此次浏览器未运行 worker、结果页或临时排版。独立安装的 HTTP 与 worker smoke 另行验证 API，不能称为浏览器结果页验收。证据见 `/tmp/drum-issue82-context/browser-final-report.json`。

## 首轮失败与修复

完整回归实际执行 251 项，用时 351.651 秒。总期限用例在 Python、CLI、HTTP 三个子项均失败，错误为 `unsupported_layout`，其余 250 项通过。旧 fixture 伪造 2×2 视频元数据，新增尺寸预检因此在启动连续解码前拒绝。修复把合成元数据改为 640×520，继续使用实际睡眠解码子进程、PID marker、进程终止和无产物断言。没有放宽总期限断言。首轮日志保留为 `regression-first.log`。

Ruff 首轮发现缓存模块七处 E701。仅展开 `managed_cache_files.py` 和 `video_cache.py` 的单行 `try`、`except`、`if`。与 `f0131af` 的无行号 AST 逐文件相同，字节 hash 已改变。前后 hash 和 AST 等价记录分别为 `format-before.json`、`format-ast-equality.json`；Ruff 原失败为 `ruff-first.log`。这两处不改变真实来源算法，已有来源证据仍准确绑定原应用提交，最终安装产物另绑定格式修复后的提交。

## 八路容量方法

容量实验只替换外部元数据和公共传输，使用 FFV1 无损可解码合成视频和真实八路 worker。640×970 合成纸面有五个不同谱行，视口序列为 `0,0,450,450`，70 像素短重叠触发实际有界补帧。每个成功任务必须有 `refinement_requests > 0`、五行、来源 hash、PDF 与全部预览 hash 断言。补帧请求不等于成功找到新增独立帧，manifest 仍记录各区间实际 added 数量。

三个单任务基线在同一服务根使用三个不同冷缓存身份，未宣称每次重新创建服务根。后续覆盖同源冷八路并取消初始获取发起任务、热八路、八个独立身份、601 秒元数据预检失败隔离，以及实际可解码全黑媒体在转换中失败的隔离。黑源独立版本与长度由传输边界提供，其他七项继续真实配准和补帧。

参数显式为 `--concurrency 8 --max-temp-mib 256 --retained-mib 16384 --min-free-mib 1 --max-rss-mib 512`，入队 `Jobs` 的空闲底线同为 1 MiB。环境允许 20 个逻辑 CPU，没有设置 cgroup 硬内存限额，`memory_hard_limit_bytes=null`。每 100ms 采样固定 PID/start-time 后代树 RSS、进程、线程、CPU ticks、cache/attempt 逻辑字节、空闲磁盘和阶段状态。SQLite 同时记录 ready 媒体字节、filling 数量和在途 reservation，传输记录完整媒体 Response.read 字节；Range 只读响应头时正文消费为零，单独记录打开次数。

首轮七波通过，后来为补齐计量而重新执行。第一次扩展实验在首个任务已完成后因 `range-bytes` 文件不存在失败，原因是合法版本检查不消费 Range 正文，外部计量脚本没有初始化零值文件。保留 `capacity-final/` 和 `capacity-final.log`，修正计量初始化，不修改产品。后续八波结果保存在 `capacity-final-2/`。该批已通过，后续仅增加 Range 打开计数后另行留证。

八波中 40 项完成、一项取消、两项受控失败。预检失败为 `resource_limit`，全黑媒体失败为 `unsupported_layout`，其他任务保持完成。热八路原缓存期限保持且无新增媒体读取。小合成视频的逻辑目录占用低于 1 GiB，不能当作整体缓存额度的硬保证；在途全额预留、持有已 unlink 媒体、未知文件和容量回退另由 `tests/test_video_cache.py` 的定向测试覆盖，包含 `test_two_inflight_sources_reserve_capacity_before_writing_media` 和 `test_unlinked_held_media_still_counts_against_cache_capacity`。本机结果不能映射为目标服务器吞吐，也未验收约两倍速度目标。

## 重放命令

在仓库根运行以下程序验证；外部证据目录每次必须使用新路径。

```sh
export PATH=/tmp/drum-issue82-env/bin:$PATH
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python ci/verify_script_product.py --output /tmp/drum-issue82-context/86/ci-replay-final
PYTHONPATH=src:tests python -m unittest test_public_contracts.ScriptPublicContracts.test_total_deadline_still_stops_continuous_decoder_in_each_entry test_video_cache -v
python -m compileall -q src/drum_score tests ci tools
ruff check --select E701,E702 src/drum_score
node --check src/drum_score/static/app.js
git diff --check
```

确定性 CI 分片 126 和 125 项，已实际核对无交集且并集恰为完整发现的 251 项，记录在 `shard-check.json`。本轮没有配置静态类型检查器，也没有把本地测试称为远端 CI 执行。

最终独立安装脚本使用无缓存构建 wheel 和 sdist，逐字节核对动态枚举的全部包文件及 `pyproject.toml`。基础和 web 两个新环境分别安装 wheel 并检查依赖，从仓库外执行 Python 与实际 `drum-score` CLI 转换。基础环境拒绝意外 FastAPI/Uvicorn，两环境确认没有 yt-dlp/EJS。web 环境启动实际 HTTP 服务及独立 worker，覆盖选段、实际 PTS、来源与全产物 hash、在线人数、缓存 hit 和原期限、临时 A3 排版及默认结果不变。停服后执行实际维护 CLI 的 backup/verify/restore，核对全部结果和 ready cache、原期限、新文件身份登记和未知 schema 拒绝。HTTP smoke 与前述真实浏览器检查分别记录。

第二次完整回归执行 251 项，用时 338.293 秒，仅 600 秒边界测试失败，预期 `incomplete_video` 而实际 `backend_version_mismatch`。该测试在同一路径、相同文件长度和同一秒内重写 `sitecustomize.py` 中的合成工具 pin。CPython 的时间戳字节码可继续加载旧 pin。独立合成重放在 `pycache-reproduction/report.json` 证实这个机制，不涉及真实凭据。修复在该测试全新 fixture 的首次子进程前设置 `PYTHONDONTWRITEBYTECODE=1`，不使用 sleep 或偏移 mtime。连续八次完整 Python/CLI/HTTP 时长矩阵通过，用时 12.223 秒。第二次完整失败日志为 `regression-final.log`，重复定向日志为 `duration-repeat-final.log`。后续仍运行完整回归，不用拼接定向通过冒充完整通过。

最终容量留证为 `capacity-final-3/report.json`，八波全部通过。Range 只观察版本响应头，正文读取为零，但打开次数独立计数如下。RSS 为外部 100ms 进程树采样峰值，单位字节；媒体读取只统计完整媒体 Response.read 返回字节，不包含 Range 头或真实网络链路开销。

| 波次 | 墙钟秒 | 运行重叠峰值 | RSS 峰值 | 线程峰值 | 媒体获取数 | 媒体读取字节 | Range 次数 | 在途预留峰值 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline-0 | 2.012 | 1 | 206794752 | 12 | 1 | 34919 | 1 | 1083495 |
| baseline-1 | 2.062 | 1 | 219795456 | 10 | 1 | 34919 | 1 | 1083495 |
| baseline-2 | 2.091 | 1 | 216481792 | 30 | 1 | 34919 | 1 | 1083495 |
| cold-cancel-leader | 5.719 | 8 | 955101184 | 47 | 1 | 34919 | 8 | 1083495 |
| warm | 5.345 | 8 | 1062232064 | 39 | 0 | 0 | 8 | 0 |
| independent-identities | 8.250 | 8 | 799698944 | 38 | 8 | 279352 | 8 | 4333980 |
| one-preflight-failure | 6.853 | 8 | 1002192896 | 46 | 0 | 0 | 7 | 0 |
| one-conversion-failure | 7.705 | 8 | 963076096 | 40 | 1 | 1901 | 8 | 1050477 |

缓存 ready 媒体峰值为 420929 字节，cache 路径普通文件峰值为 441079 字节，attempt 路径普通文件峰值为 3847766 字节。各波保留完整阶段 timeline、文件用量、ready/reservation/filling、空闲磁盘及逐任务资源。热缓存八项全部为 hit，expires_at 逐项等于冷缓存发布期限。冷缓存 leader 被取消后共享获取继续，七项成功；最后两波各有七项成功。共 40 项完成，全部保留五行和实际补帧请求证据。

## 最终源码回归结果

Python 3.12.12 下第三次完整发现 251 项全部通过，用时 347.734 秒，没有跳过，完整日志为 `regression-final-2.log`。此轮包含修复后的两份测试 fixture、新增公开组合测试，以及 AST 等价的缓存格式修改。此前 19 项期限和缓存定向验证用时 90.685 秒通过，日志为 `targeted-final.log`。连续八次时长公开矩阵与最终完整回归分别记录，不省略前两次失败。

离线 CI 合成重放通过，用时 2.304 秒，输出在 `ci-replay-final/`，命令状态在 `final-verify.json`。该文件中的第二项仍为第二次完整回归的真实失败记录，最终完整回归结果以 `regression-final-2.log` 为准。Ruff 0.14.14 的 E701/E702、Python 编译、JavaScript 语法和 `git diff --check` 均通过。最终分片仍为 126 和 125 项，测试修复没有改变发现集合。

本提交先交付源验证，最终 wheel 构建、基础/web 独立安装与安装后真实来源/浏览器验证等待独立审查结论后执行。前文安装段描述已准备的验证脚本，不表示这些安装检查已经通过。
