# 日志部署复盘改进验证

本轮把日志部署中实际出现的基线冲突、构建污染和失败恢复问题转为版本化工具。基线为 `ef7444f`，包含已部署的记录整合及后续 Issue #88 集成；独立工作区为 `/home/kenqia/my_folder/bilibili-drum-retro-guardrails`，分支 `codex/retro-guardrails`。没有改动原工作区的配准修改、独立 Skill 或正在运行的服务器，没有远端写入。

## 实现与入口

[运维入口](../script-product/operations.md)统一兼容关系、发行、升级与恢复导航；AGENTS 仅增加条件入口，原文件副本保存在本地证据根。

- `tools/service_baseline.py`：只读部署 commit、规范化 schema 结构及显式配置 hash；候选 checkout 可验证转移清单的祖先关系和结构兼容，不依赖目标机路径或媒体包。
- `tools/build_release.py`：指定 commit 的干净 Git 导出；wheel、sdist 包文件集合和字节核验；提交、包文件及制品 SHA-256 清单。现有 offline workflow 新增同入口 `release` job。
- `tools/deploy_release.py`：默认只读预检，显式执行已经备份/升级好的根；代码、配置、数据成组切换；私有端口和有效 systemd 命令核验；开放后的失败保留新数据并停止 web 接收。
- `tests/record_contracts.py` 和缓存测试：HTTP、真实 worker、合成媒体，核对下载、缓存、共享失败、取消、重试的结构化记录和完整发布 manifest。

## 验证方式与证据

本地证据根为 `work/engineering/2026-10-28-retro/`。使用项目已有 Python 3.12.12 独立环境，`PATH` 指向该环境，`PYTHONPATH=src:tests`，`OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1`。真实解码回归与 CI 重放串行执行。

工具专项命令为 `python -m unittest test_release_guardrails -v`，最终代码 `487936c` 的 17 项通过，7.637 秒，见 `guardrails-complete.log`。覆盖同号异构、配置漂移、非祖先提交、转移基线、陈旧/缺失/修改包文件、配置及链接发布后 fsync、报告故障、已有/替换 symlink、外部等字节配置替换、私有监听参数等号和缩写绕过、实际 systemd 覆盖、私有失败恢复及公开失败保留新根。

`python -m unittest discover -s tests -v` 的 308 项在 739.840 秒内全部通过，无跳过，见 `full.log`。首次全回归从 `d783256` 启动，之后只修正工具和工具测试；应用包与日志矩阵文件未改变。最终工具版本另以上述 17 项验证，不能将全回归描述为后来新增测试的同一次发现。

准确代码 `487936cdf682e978f71edfb05df6d7dbd188e713` 使用唯一构建入口成功输出 wheel/sdist，45 个包文件在两种制品中与提交字节一致，见 `build-complete.log` 和 `release-complete/release-identity.json`：

| 制品 | SHA-256 |
| --- | --- |
| wheel | `7f92e9d29325d49e1bc3fab9e03abb5a10265e5b372d7111d9ad13862d86b5e5` |
| sdist | `e9da90912197a9fc02d0e17da937ae2a200a44b91ac1d22b79df16923a0b3390` |

构建工具隔离环境产生的 setuptools 静态资源目录发现提示保留在日志中；构建和逐文件校验均成功。基础程序包未变，本轮不重复两套安装版媒体验收。

`python ci/verify_script_product.py --output work/engineering/2026-10-28-retro/replay` 通过：合成三行、一页、三张嵌入图，重复重放 PDF 相同，输出已存在和资源超限拒绝；见 `replay.log` 和 `replay/summary.json`。

`python3 tools/service_baseline.py --help` 在系统 Python 下通过，证明基线工具不需要导入 numpy/OpenCV。Ruff E701/E702、compileall 和 `git diff --check` 通过；没有新增类型检查配置，不冒称运行静态类型检查。远端 CI 尚未执行。

## 审阅与限制

两路独立审阅发现报告覆盖/链接跟随、外部 current 与等内容 profile 身份替换、私有监听约束和 worker 配置不一致。修复后补上报告 exclusive/no-follow 与持有 FD、发布/恢复身份核对、严格受保护参数和有效 ExecStart 核验。Spec 后续复核还发现等号及 argparse 缩写绕过，已以完整独立 token 限定修复并回归。两路审阅最终均确认原发现关闭，无阻断项。

故障注入使用临时文件、真实 SQLite 和合成 systemctl 边界，不是目标机断电、systemd 切版或实际生产部署验收。工具处理进程内异常；整进程 SIGKILL 或断电后按私有 rollback 材料人工核对恢复。没有新增真实来源或音乐校对；原生产期限和配置保持原状。
