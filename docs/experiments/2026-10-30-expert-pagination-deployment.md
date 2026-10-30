# 专家兜底与谱行分页正式部署

2026-10-30，按用户明确决定发布专家 v6 失败兜底、谱行边界与分页改进。正式发行切换至 `61b5f24073a532d6e3fbd0338173cf748e1fb8dc`，数据根为 `/var/lib/drum-score-restore/approved-20261030-r2`，schema v5。公网真实转换、全部下载及取消验收通过。

## 范围与实验取舍

程序代码与已推送的 `c3e2ded` 一致，发行提交只增加发布范围文档。首选转换继续沿用回退后的稳定算法，分页使用已验收的边界细分；只有默认网站任务的 `unsupported_layout`、`discontinuity` 才触发专家兜底。高级选项、Python 与 CLI 不启用专家路线。

用户将 YouTube 运营者账号获取、新整理算法、翻页、真实像素恢复和性能优化全部定为放置中，不使用、不合并、不部署。分支、未提交性能改动、媒体和实验保留，各工作区交接已标注状态。具体版本见[发布范围](../script-product/release-status.md)。本次不修改独立 Skill、认证、DNS、TLS 或其他应用。

用户同时要求删除两项旧改动。本轮在原 `codex/discontinuity-recovery` 工作区恢复已核对的 11 个跟踪文件，移除未跟踪的 `alignment.py`、`test_alignment.py`，保留其他未知文件和实验。S06 下缘去重在 quality 工作区以本地提交 `1fe74cd` 撤回，移除实现及专属测试，保留同提交加入的通用公开滚动、来源 RGB 和下载断言。撤回后 `row_collection.py` 与 `1772100` 的父版本逐字节一致，语法及 diff 检查通过。该放置中分支没有推送或部署，也没有重跑整套实验回归。

## 本地与安装验证

使用现有 Python 3.12.12 独立环境，将其 bin 放到 PATH 首位。真实解码验证顺序执行。

```sh
python -m unittest discover -s tests -v
python tools/build_release.py --commit 61b5f24073a532d6e3fbd0338173cf748e1fb8dc --output ABSOLUTE_NEW_OUTPUT
python ci/verify_script_product.py --output ABSOLUTE_NEW_EVIDENCE
python -m compileall -q src/drum_score tests ci tools
ruff check --select E701,E702 src/drum_score
node --check src/drum_score/static/app.js
git diff --check
```

完整程序回归 321 项、484.695 秒全部通过，无跳过。此前整理记录 CLI 的旧包加载问题在本次完整发现中通过。离线 CI 合成重放通过，三行一页、三份嵌入图像、两次 PDF 相同，输出不覆盖和资源拒绝保留。编译、所列 Ruff 规则、JavaScript 语法及 diff 检查通过。未配置静态类型检查器，未执行独立 Skill 回归，未核验本次远端 CI 的最终结果。

从准确提交构建 wheel 和 sdist，两个制品的 56 个程序包文件与源码逐字节一致：

| 制品 | SHA-256 |
| --- | --- |
| wheel | `7b8d40b332e958385c0ea6bd738c4a4f8c697ee818704f0462d77de7fe1fcc5f` |
| sdist | `a87297ac4ce429dfc9418bd376e1e9372d0e38992b691a46323c0536adf0ca08` |

本地新建基础版、web 版两个独立环境，离线安装现有版本的依赖。56 个安装文件各自匹配制品，依赖检查通过。基础版没有 FastAPI/Uvicorn，从仓库外运行 Python 和实际 CLI 合成转换，核对来源 hash、实际 PTS/time_base、PDF 和全部预览。web 安装版从仓库外通过实际 worker 触发合成专家转换，核对下载、临时排版、backup/verify/restore 往返及默认结果和期限不变。

## 服务器准备与数据保护

现场六份 unit/drop-in 的 hash、旧发行 `ee8ce0b`、schema v5 与候选祖先关系核对通过。新发行使用独立 venv，运行依赖复用当前正式发行的同版本公共包；安装文件核验、`pip check` 及固定 BBDown hash 通过，没有升级系统依赖。

首次安装沿用历史 wheelhouse 路径，但该目录已不存在，命令在新发行目录失败，正式服务未受影响。失败目录保留为服务器准备根下的 `failed-install-v1`，随后从新目录完成安装。

切版前暂停新提交，等待活动转换及临时排版排空，再停止 HTTP 和 worker。使用候选维护工具执行完整 backup、verify、restore，恢复到不存在的新根，逐项比较：

| 数据 | 原记录数 | 核对内容 |
| --- | ---: | --- |
| 任务 | 741 | 身份、选项、完成与到期时间 |
| 缓存 | 91 | 身份、发布时间、到期时间、媒体 hash |
| 整理记录 | 1309 | 状态、完成与到期时间、记录内容 |
| 提交计数 | 175 | IP 摘要及准入时间，仅内存比较 |
| 接收控制 | 1 | 暂停状态 |

恢复前后全部比较一致，没有刷新期限。数据及记录正文没有导出到文档。

首次准备在配置路径计数断言处中止。脚本错误地假定数据根只出现一次，实际配置在多个位置引用同一根。旧服务与原接收状态已恢复，未切换发行。修正该准备脚本后重新备份并恢复到 `approved-20261030-r2`，没有复用首次快照。首次失败证据及恢复副本保留。

## 私有端口与公网验收

通过仓库 `tools/deploy_release.py` 先只读预检，再执行切换。工具核对停服数据库 hash、安装包文件、配置身份和 systemd 实际命令，在 8792 私有端口完成真实任务验收后才开放 8791。

| 真实来源 | 路线 | 含下载、核验和临时排版的时间 | 结果 |
| --- | --- | ---: | --- |
| `BV1rH4y1R7Rk?p=1` | 首选算法 | 67.856 秒 | 两页 |
| `BV1G84y1S79S?p=1` | 专家 v6 兜底 | 48.748 秒 | 三页，显式待复核警告 |

两条任务的 PDF、全部预览逐一核对字节数与 SHA-256，复制到本地后再次核对，五页预览均实际查看。首选结果标题和末页可见；专家结果保留大灰水印、页面边缘杂项及灰度处理，不宣称自动去水印或音乐完整性通过。两条任务的 A5 临时排版、默认 PDF 与原期限不变、604800 秒整理记录通过。另验证高级选项任务取消、显式重试、再次取消及记录独立性。

公网另提交一条默认真实来源，含轮询及全部下载 69.818 秒完成，两页 PDF/预览 hash 全部匹配。独立公网提交、无凭据查询 404、认证查询及取消通过，WSL HTTPS 返回 200，TLS 验证成功。能力凭据只保留在验收进程内存，不写脚本、日志或任务链接。

最终现场 web、worker、nginx、zju-search 均 active，schema v5、暂停状态 0、`record_failed=0`。20 次 HTTPS 探针均为 200，web/worker 无自动重启或 OOM。两份 profile 与原件的差异仅为新数据根，其他四份配置 hash 不变。原 20 GiB 逻辑额度、512 MiB 单任务临时额度、1 GiB 媒体缓存、256 MiB 整理记录、24 小时结果期限和一周记录期限保持。worker 仍为 1 GiB/150% CPU、web 为 256 MiB/50% CPU。最终资源快照不作为并发容量测试。

所有程序结果保持 `reliable=false`。本轮没有逐符号音乐校对或新一轮 48 源批量运行。此前 48 源已在独立批次完成，46 份 PDF、140 页，20 份首选、26 份专家、两例失败；历史接入记录中的未执行状态不代表该批次后续状态。

## 回滚与留证

旧发行 `/srv/drum-score/releases/ee8ce0b5962d8f21e98fed16eb2b0ed761498e1d`、旧根 `/var/lib/drum-score-restore/rollback-20261028-r2` 均保留。最终核验快照为 `/var/backups/drum-score/backup-before-approved-20261030-r2`，配置与计划在 `/srv/drum-score/deployment-approved-20261030/deployment.rollback/`。

公网开放后已有新任务，不能直接用旧数据库覆盖新根。若需回滚，先暂停新提交、排空并保存当前新任务，再按[运维入口](../script-product/operations.md)准备配套恢复方案。本轮只在首次准备失败时恢复了旧服务，没有在成功开放后回退。

本地完整证据位于 `bilibili-drum-main/work/engineering/2026-10-30-release-approved/`。`full-regression.log`、`verification.json`、`release/`、两份安装 smoke 报告、`preparation.json`、`acceptance.json`、`deployment.json`、`public-smoke-events.jsonl`、`public-cancel.json`、`postcheck-final.json` 和两组公开来源产物分别记录本地、合成、真实来源、实际看图和最终运行状态。
