# #73 生命周期与产品收口

2026-10-21 开始，2026-10-22 完成本地实施。工作树 `/home/kenqia/issue73-product`，分支 `codex/issue-73-product`，基线 `9b85b0f4e3c5a7b0fabc48ed76dfdbb4a9b0597d`。最终提交与源码身份绑定保存在外部证据 `product73-packaging/final-binding.json`，不把实施前 HEAD 当作交付提交。

## 改动与边界

网站 schema 版本为 1。空库可初始化，未知版本或旧未版本化库拒绝启动。worker 在领取前、结束后清理；到期先持久化 expired，再按登记的 device/inode/ctime 清理受管文件。未知文件、替换目录、替换文件与 symlink 保留。合法已打开的 Linux FD 在 unlink 后继续读取，新的请求按原期限返回 410。同大小下载损坏也经 SHA256 校验拒绝。

准入、显式重试和领取检查 attempts 全目录逻辑字节与单任务暂存预留，运行中检查总额和磁盘底线。不删除仍有效的结果来接受新任务。失败诊断另有时间和总文字额度。网站结果清理原生帧、长图及获取暂存，保留实际 PTS/hash，并明确 `can_reconstruct_from_retained_sources=false`。core 原子发布后、inventory 登记前遭 SIGKILL 的窗口会在恢复时校验生成清单并清理，不接管未知文件，也不自动成功。

四个下载/解码复用模块迁入 `drum_score`。仓库内 Skill、专属安装工具、人工批准/生成恢复入口及专属测试退役，已安装 Skill、实验、媒体与原工作树用户修改保留。旧 217 个测试的逐项去向见[迁移表](../test-migration.md)。无生产依赖新增，无自动任务迁移。

supervisor 与 guardian 固定进程初始 start-time，已跟踪 PID 不覆盖身份，根进程退出后也不重新认领复用 PID 的进程树。真实 sentinel 进程配合外部 `/proc` 观测替身先复现被误杀，再证明修复后存活。复用后代 PID 的红例保存在 `pid73-descendant-red.log`。没有增加生产测试钩子。

## 本地验证

统一使用 `/home/kenqia/issue72-web-venv/bin/python`，并将其 `bin` 放到 `PATH` 首位，避免 `env python3` 使用 Conda 3.13。最终命令：

```sh
PATH=/home/kenqia/issue72-web-venv/bin:$PATH PYTHONPATH=tests:src \
  /home/kenqia/issue72-web-venv/bin/python -m unittest discover -s tests -v
PATH=/home/kenqia/issue72-web-venv/bin:$PATH PYTHONPATH=tests:src \
  /home/kenqia/issue72-web-venv/bin/python ci/verify_script_product.py \
  --output /home/kenqia/issue69-context/ci73-final
/home/kenqia/issue72-web-venv/bin/python -m ruff check --select E701,E702,F821 src/drum_score tests ci tools
/home/kenqia/issue72-web-venv/bin/python -m compileall -q src/drum_score tests ci tools
git diff --check
```

最终完整回归 131 项，109.065 秒，无失败或跳过，日志 `/home/kenqia/issue69-context/full73-budget-final.log`。此前 130 项、111.122 秒的 `full73-final.log` 与首次 127 项 `full73-first.log` 均保留，不替代最终结果。Ruff、compileall 与 diff 检查通过。CI 两分片分别 66/65 项，无交集，完整覆盖 131 项，报告 `shards73-budget-final.json`。纯程序重放双跑实际 PDF、全部预览、来源与拒绝检查通过，报告 `ci73-final/summary.json`。未执行远端 CI。

预检最初发现 HTTP 预览失败、PDF 跨页实际比例、未知操作保护用户文件三处覆盖缺口，已补充真实后果断言并包含在最终全回归。core 发布窗口测试初次因测试 startup 缺少 `import os` 没有到 marker，补齐后通过；未将未到阶段当成功。旧跨阶段预算协议退出，手动向夹具填入 60 的测试只说明受控失败保护文件。新增真实 FFmpeg 替身进程测试从近预算状态开始，实际等待 0.15 秒失败后由生产单调时钟累计；第二个计划等待 10 秒的进程按剩余额度被停止，第三次耗尽不启动。只种初始已用额度，不手写新增耗时，专项 `budget73-real.log` 为 1 项、0.853 秒通过。真实总期限由六项获取生命周期和转换进程测试另行验证。

## 独立安装

证据目录 `/home/kenqia/issue69-context/product73-packaging`。`build.py` 从准确产品源码创建干净 stage，`uv build --sdist --wheel --no-cache` 构建。20 个包文件含三份静态资源在源码、sdist、wheel、两份独立安装间逐字节相同。发行包不含旧 Skill、实验或顶层复用模块。

- wheel SHA256：`6d14ee43ce7860b8918b1c09197e1d390dc5422ba95e62d6000d428806edcc59`
- sdist SHA256：`8e64caffb25a439d5050b26f52d64027c280638c2f0f18cb861d6ad54644e3b5`
- 基础环境：`/home/kenqia/issue73-base-venv`，Python 3.12.12，未安装 FastAPI/Uvicorn。
- web 环境：`/home/kenqia/issue73-installed-venv`，Python 3.12.12。

在仓库外 `/tmp` 清除源码 `PYTHONPATH` 后分别执行 `smoke.py`，两环境 CLI 实际转换合成视频，核对源 hash、实际 PTS、PDF 与全部预览。web smoke 另以实际 HTTP CLI 和独立 worker 处理公开链接格式的合成网络来源；仅子进程局部加载外部网络替身，没有源码路径。实际等待 2 秒保留期后，任务/PDF/预览均 410，受管 PDF/manifest 物理清除。两环境 `uv pip check` 通过。详情为 `identity.json`、`base-smoke-report.json`、`web-smoke-report.json` 和对应日志。

首次 smoke 使用了错误的 CLI `page_count` 键，随后按 `pages` 长度检查；web 首次误把 Uvicorn 收到 SIGTERM 后的 `-15` 退出当失败。修正验收脚本后重跑通过，实际退出码保留在报告。原失败日志不删除。以上未修改生产代码，因此 wheel 身份保持。

## 安装版真实浏览器

Root 在 2026-10-22 从最终 wheel 安装环境运行真实匿名小星星，实际完成网页提交、排队取消、显式重试、运行中 SIGTERM/interrupted、再次重试、关闭后返回、全部一页预览与按钮下载。PDF SHA256 为 `8064538f70851edc4f66702ea2bdf979d1188411c1c222f2d125a56523b873c2`，与桌面放大均衡版一致。用户认可原谱面后要求放大和均衡分页，已按要求交付。显式使用 20 秒保留期后，状态/PDF/预览均 410，产物物理删除，未改变默认 24 小时或主机时间。

实际查看桌面与 390 宽首页、结果和过期页共五张截图，没有溢出或脚本异常；两项 console 来自故意 422 与到期 410。100ms 采样 web/worker 树 RSS 峰值 375308288 字节，仅为 WSL 采样，排除浏览器和 harness。报告 `/home/kenqia/issue69-context/browser73-installed-final-report.md`，明细 `evidence/website73-installed-final/browser-report.json`。Root 回执 session22399 exit0，端口 48861 无监听，服务已停止；截图遮盖能力链接，凭据不写日志。

## 未完成的验收

合成转换和程序化 PDF 检查不证明新的真实来源完整性或逐符号音乐校对。四曲原谱面已获用户认可，随后按要求交付放大均衡版，尚无另一次质量回执；本轮没有新模型调用。浏览器验收不代表逐符号音乐校对或所有视频均可成功。目标服务器硬资源、备份核验恢复、正式反向代理、DNS/TLS 与公开部署属于 #74；没有远端写入、push、PR、关闭工单或合并 main。
