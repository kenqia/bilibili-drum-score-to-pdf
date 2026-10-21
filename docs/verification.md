# 验证

当前产品是 `drum_score` Python 包、`drum-score` CLI 和可选的匿名网站。安装依赖和运行方式见[安装指南](install.md)。旧 Skill 的历史测试与验收通过 [#72 集成版本的验证记录](https://github.com/kenqia/bilibili-drum-score-to-pdf/blob/9b85b0f4e3c5a7b0fabc48ed76dfdbb4a9b0597d/docs/verification.md) 和保留的 `docs/experiments/` 查看，不作为当前产品的新验收。

## 运行回归

使用 Python 3.12 和独立虚拟环境。FFmpeg、FFprobe 与 Poppler 必须在 `PATH` 中。安装基础包、web extra 和测试 HTTP 客户端后运行：

```sh
python -m pip install '.[web]' -r tests/requirements-web.txt
python -m unittest discover -s tests -v
python ci/verify_script_product.py --output work/ci-evidence
python -m compileall -q src/drum_score tests ci tools
```

开发环境必须把该环境的 `bin` 放到 `PATH` 首位，以使测试创建的 `env python3` 子进程使用同一解释器。不要并发执行多套真实解码或批量预览测试。

CI 使用 Python 3.12。Linux 完整发现由两个确定性分片覆盖，分片并集必须等于完整发现且无交集：

```sh
python ci/run_unittest_shard.py --index 0 --count 2 --list
python ci/run_unittest_shard.py --index 1 --count 2 --list
```

Windows CI 运行原生工具检查、跨宿主解码、公开入口共同约束和合成转换重放。Linux 服务进程契约不作为 Windows 服务支持声明。本地检查不代表远端 CI 已执行。

## 核对行为与证据

`tests/test_public_contracts.py` 是公开入口的共同约束矩阵。新增或改变 Python、CLI、HTTP 的公开能力时，把适用入口加入同一矩阵；HTTP 只接收公开链接，本地文件只适用于 Python 和 CLI。共同约束覆盖来源与资源拒绝、输出不覆盖、完整预览、来源 hash、实际 PTS，以及 `reliable=false` 的完成结果。

`tests/test_acquisition_lifecycle.py` 和 `tests/test_web_worker.py` 使用真实独立进程与 OS 信号。离线网络只替换外部传输边界；阶段 marker 必须证明测试确实进入待停止阶段。PID 复用测试替换 `/proc` 观测后检查真实 sentinel 进程，不能只断言调用了 mock。

`tests/test_product_lifecycle.py` 覆盖 schema 拒绝、期限不刷新、到期文件清理、已打开 FD、容量准入、诊断限额、文件身份与 symlink 边界、同大小产物损坏。worker 的崩溃恢复必须覆盖发布前后，未登记的用户文件保留。

谱面测试检查首尾、重复音乐、原生运动歧义、连续条带、实际 PDF 嵌入像素及跨页比例。轮廓和图像拼接不证明音乐识别或逐符号准确性。受控失败的预算值不能当作实际解码耗时；真实总期限测试单独提供进程停止证据。

旧 217 项直接测试的最终去向见[测试迁移表](test-migration.md)。退役只适用于已退出的 Agent 批准、宿主生成、手动重建、MIDI 和 Skill 分发协议。匿名网络、期限、输出、文件与谱面完整性约束继续由当前测试或安装验收承接。

## 验证安装产物

从准确源码无缓存构建 sdist 和 wheel，逐字节核对所有包文件与三份静态资源。分别创建基础安装和 web extra 环境，从仓库外运行，清除源码 `PYTHONPATH`。基础环境确认未安装 FastAPI/Uvicorn；web 环境实际启动 HTTP CLI 和独立 worker。两者运行依赖冲突检查、合成转换、全部预览、来源 hash 与 PTS 核对。安装报告必须记录解释器、包 hash 和源码身份，源码有变时重新构建。

网站的缩短保留期测试须记录真实参数，实际等待到期，检查状态、PDF、预览统一返回 410，并检查受管文件物理删除。恢复任务不得刷新原完成时间或原期限。备份恢复若重建文件，须在清单/hash 核验后重新登记新 inode/ctime 身份。

## 当前结果与限制

#73 的命令、日志、安装身份及失败过程见[产品收口实验记录](experiments/2026-10-21-issue73-product.md)。此前 #70/#71 的四曲放大 PDF 已获用户认可；#73 没有新的逐符号校对或模型生成。Root 已在最终 wheel 独立安装上完成真实匿名小星星浏览器验收，包含取消、重试、SIGTERM 中断、关闭后返回、全部预览、实际下载及显式 20 秒到期物理清理，详情见实验记录。服务器硬资源、备份部署、公开域名与 TLS 属于 #74，当前本地结果不替代这些验收。
