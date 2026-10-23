# 验证

本页验证 `drum_score` Python 包、`drum-score` CLI 和可选的匿名网站。安装依赖和运行方式见[安装指南](install.md)。同仓库的 Skill 使用独立依赖和 `tests/skill/` 测试，命令见 [Skill 验证](skill-verification.md)。两套测试需在不同 Python 进程中发现，避免同名 fixture 和模块相互污染。

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

`tests/test_public_contracts.py` 是公开入口的共同约束矩阵。新增或改变 Python、CLI、HTTP 的公开能力时，把适用入口加入同一矩阵；HTTP 只接收公开链接，本地文件只适用于 Python 和 CLI。维护 backup/verify/restore 共同覆盖真实 pdftoppm 十页补零文件名与顺序、全页 hash 往返及重复/错序/穿越/额外页拒绝，也覆盖参数脱敏、来源路径拒绝、资源与 schema 拒绝及失败时源文件不变。转换共同约束覆盖来源与资源拒绝、输出不覆盖、完整预览、来源 hash、实际 PTS，以及 `reliable=false` 的完成结果。

`tests/test_acquisition_lifecycle.py` 和 `tests/test_web_worker.py` 使用真实独立进程与 OS 信号。离线网络只替换外部传输边界；阶段 marker 必须证明测试确实进入待停止阶段。PID 复用测试替换 `/proc` 观测后检查真实 sentinel 进程，不能只断言调用了 mock。

`tests/test_product_lifecycle.py` 覆盖 schema 拒绝、期限不刷新、到期文件清理、已打开 FD、容量准入、诊断限额、文件身份与 symlink 边界、同大小产物损坏。worker 的崩溃恢复必须覆盖发布前后，未登记的用户文件保留。

`tests/test_maintenance.py` 覆盖一致快照、完整多页结果、正式 worker 恢复、原期限及新身份清理、锁与真实 HTTP 写屏障、schema/路径/文件完整性、容量/期限，以及复制、清单写入、发布前的实际 SIGKILL。ENOSPC、子目录 fsync 与发布后父目录 fsync 使用仅作用于合成子进程的外部 I/O 故障注入，不代表真实断电。整服务树 SIGKILL 包含 guardian，恢复须清理确切受管临时根，保留未知根、attempt 文件及身份替换物。

谱面测试检查首尾、重复音乐、原生运动歧义、连续条带、实际 PDF 嵌入像素及跨页比例。轮廓和图像拼接不证明音乐识别或逐符号准确性。受控失败的预算值不能当作实际解码耗时；真实总期限测试单独提供进程停止证据。

#73 将旧测试语义迁入程序时的处理见[历史迁移表](test-migration.md)。恢复的 Skill 测试单独位于 `tests/skill/`，其 Agent 审阅和恢复语义不适用于程序与网站。匿名网络、期限、输出、文件与谱面完整性保护分别由各自产品的测试承接。

## 验证安装产物

从准确源码无缓存构建 sdist 和 wheel，逐字节核对所有包文件与三份静态资源。分别创建基础安装和 web extra 环境，从仓库外运行，清除源码 `PYTHONPATH`。基础环境确认未安装 FastAPI/Uvicorn；web 环境实际启动 HTTP CLI 和独立 worker。两者运行依赖冲突检查、合成转换、全部预览、来源 hash 与 PTS 核对。安装报告必须记录解释器、包 hash 和源码身份，源码有变时重新构建。

网站的缩短保留期测试须记录真实参数，实际等待到期，检查状态、PDF、预览统一返回 410，并检查受管文件物理删除。恢复任务不得刷新原完成时间或原期限。备份恢复若重建文件，须在清单/hash 核验后重新登记新 inode/ctime 身份。

## 当前结果与限制

#73 的命令、日志、安装身份及失败过程见[产品收口实验记录](https://github.com/kenqia/bilibili-drum-score-to-pdf/blob/8c8730a4c3defa2fb317897a648ebc3ef66b4273/docs/experiments/2026-10-21-issue73-product.md)。此前用户认可 #70/#71 的四份原谱面后要求放大和均衡分页，已按要求交付；#73 没有新的逐符号校对或模型生成。Root 已在最终 wheel 独立安装上完成真实匿名小星星浏览器验收，包含取消、重试、SIGTERM 中断、关闭后返回、全部预览、实际下载及显式 20 秒到期物理清理，详情见实验记录。服务器硬资源、备份部署、公开域名与 TLS 属于 #74，当前本地结果不替代这些验收。


#74 本地维护和部署演练见[维护实验记录](https://github.com/kenqia/bilibili-drum-score-to-pdf/blob/8c8730a4c3defa2fb317897a648ebc3ef66b4273/docs/experiments/2026-10-22-issue74-maintenance.md)。该阶段全量 148 项通过，无跳过；新 wheel 已完成基础/web 离线安装、仓库外维护恢复正式服务及真实小星星浏览器验收。恢复演练保留原期限并实际等待 4 秒到期；浏览器另用 20 秒。两者均检查状态/PDF/全部预览 410 与物理删除，不代表默认保留期已改变。后续目标机安装、unit 启动、独立 cgroup 限额探针、域名/TLS、续期及停服备份核验见[部署状态记录](https://github.com/kenqia/bilibili-drum-score-to-pdf/blob/8c8730a4c3defa2fb317897a648ebc3ef66b4273/docs/experiments/2026-10-22-server-deployment.md)。该轮因服务器 B站匿名获取 HTTP 412 保留待开放。后续按用户要求换为 BBDownNext 2.3.0 并恢复部署，最新目标机与公网结果见下节。

`tests/test_comparison_tool.py` 从真实工具 CLI 验证冻结程序的实际源码目录，拒绝 main 历史脚本的已跟踪修改和未跟踪影子模块，保留优化版 src/pyproject 约束。合成 Git fixture 不运行媒体，不重算历史四曲比较数据。

最终审阅的补零页名备份与比较工具冻结目录修复见[双轴审阅修复记录](https://github.com/kenqia/bilibili-drum-score-to-pdf/blob/8c8730a4c3defa2fb317897a648ebc3ef66b4273/docs/experiments/2026-10-22-final-review-fixes.md)。原 #74 浏览器证据只沿用到字节未改的 web/worker/核心，新维护代码另以新安装环境的十页 PDF 往返验收。


## BBDownNext 接入与公网验收

2026-10-22 的 0.1.1 发行基于应用提交 `538f758`，wheel SHA256 为 `3cd4e6caec9b64bced0e41ae71df26028758477d4a920fcfa402a9f76cae28e8`。169 项全回归 116.421 秒通过，无跳过；离线 CI 合成重放、基础/web 两份独立安装、25 个包文件字节核对和双轴审阅通过。

腾讯云在 cgroup 512 MiB worker、128 MiB web 下完成真实小星星直连转换、取消、SIGTERM 后重试、全部预览/PDF、备份恢复、原期限和实际 410/物理删除；另在目标机验证合成十页备份恢复。公网 HTTPS 的独立浏览器提交、关闭后返回、全部预览与下载通过，默认保留期 24 小时。缩短的 45 秒恢复测试与 20 秒浏览器到期测试只作用于隔离数据。完整证据、失败和回滚记录见[接入实验](https://github.com/kenqia/bilibili-drum-score-to-pdf/blob/8c8730a4c3defa2fb317897a648ebc3ef66b4273/docs/experiments/2026-10-22-bbdown-integration.md)。这不是所有 B站视频或音乐逐符号准确性的保证。


## 同仓库独立产品回归

2026-10-22 恢复独立 Skill 后，程序与网站171项回归126.861秒、无跳过通过，Skill另在独立依赖环境中186项通过、两项Windows专属检查在Linux跳过。分发包和仓库外转换、依赖隔离、双轴复核见[独立产品验证](https://github.com/kenqia/bilibili-drum-score-to-pdf/blob/8c8730a4c3defa2fb317897a648ebc3ef66b4273/docs/experiments/2026-10-22-independent-products.md)。网站应用文件未变，本轮不重复B站下载或生产部署。

## 八路并行本地验证

2026-10-23，Python 3.12.12 下程序 198 项回归全部通过，耗时 138.414 秒。离线 CI 重放、构建、29 个包文件核对、基础与 web 独立安装及依赖检查通过。测试实际运行八个转换进程，覆盖取消隔离、信号与 guardian 清理、SQLite 竞争、维护锁、v1 到 v2 升级和原结果期限。

本地离线合成八路实验最慢处理耗时为独占中位数的 3.31×、2.38× 和 2.13×，CPU 拓扑和设置各不相同，不能直接映射为云服务器规格。八路约两倍目标尚未验收，没有执行本轮生产部署、生产压测或新的真实来源音乐验收。方法、命令、安装包 hash、失败过程和完整证据路径见[并行容量实验](experiments/2026-10-23-parallel-capacity.md)。
