# 最终双轴审阅修复

独立审阅在集成 `e8d278cc3f6677baf54eb3b37c3a41c1109a8f1a` 上复现两项缺陷。本轮在 `/home/kenqia/issue69-review-fixes` 单一实施者修复，不执行远端写入或重新运行四曲性能比较。原 #74 包、安装环境和真实浏览器证据完整保留。

## 十页以上结果的备份

真实 pdftoppm 对十页 PDF 生成 `page-01.png` 至 `page-10.png`。既有 worker 校验与页面读取接受这组合法产物，但维护工具按 `page-1.png` 重建名称并拒绝前导零，导致 backup 返回 `invalid_snapshot`。独立微型 PDF 复现用时 0.172 秒，不涉及视频解码或真实网络，证据在外部 `/home/kenqia/issue69-context/final69-standards-repro.{py,jsonl}`。

修复仅调整维护层。它沿用 manifest 的实际预览名称，核对名称为页文件且数字页号从 1 按列表顺序连续递增，复制和恢复时不重命名。快照路径白名单允许补零名称。重复页、错序、路径穿越和额外文件继续拒绝。

`tests/test_public_contracts.py` 的公开维护矩阵使用真实 reportlab 十页 PDF 与 pdftoppm，通过实际 backup/verify/restore CLI、原摘要及每页读取 hash 核对往返。坏清单测试同步更新数据库摘要和快照 SHA-256，避免仅因旧 checksum 失败而掩盖语义校验。原一页及无前导零结果继续由现有回归承接。

## 比较工具的源码冻结

main adapter 从历史 checkout 的 `skills/bilibili-drum-score-to-pdf/scripts` 导入。迁包后版本检查却只看 `src` 和 `pyproject.toml`，因此历史脚本已跟踪修改或未跟踪影子模块可能越过冻结检查。修复按 program 选择实际加载目录，main 检查历史 scripts，optimized 保留 src/pyproject 约束，完整提交检查不变。

`tests/test_comparison_tool.py` 在临时合成 Git 仓库调用真实工具 CLI，覆盖两种 main 变化以及优化版 src、pyproject 和影子模块变化，均须在创建输出前拒绝。清洁源码对照越过版本检查，但输入集合为空，不执行媒体。这些检查不改变或冒充历史四曲比较结果。

## 验证与证据边界

两个公开入口测试实际先 RED 后 GREEN，GREEN 为 2 项 1.631 秒。证据 `review69-fixes-{red,green}.log` 位于外部证据根。静态 Ruff E701/E702/F821、compileall 与 diff check通过。新鲜完整回归为 150 项、113.872 秒、全部通过且无 skip，日志 `review69-full-final.log`。确定性分片 75/75 穷尽且无交集。

新包和安装绑定保存在 `/home/kenqia/issue69-context/review69-packaging/`，保留原 `deployment74-packaging/`。与原最终 wheel 的 23 文件逐字节比较，只有 `maintenance.py` 改变，22 个核心、网络、web、worker 和静态文件保持相同。此前真实浏览器证据只用于这些未改代码；新维护行为以新安装环境中的十页真实 PDF 往返与坏输入拒绝单独验证，不能把旧浏览器报告称为新包整体验收。

新 wheel SHA-256 为 `428771b64b42447ae12225bdceb5ad9ee41de84e341a0aef59e2de402f9d1dd4`，sdist 为 `7d9be8f98860d1d85602d5fa0fd812fcb96f5b4e09d9b92119fa6c014e6ef17c`，23 包文件与源码/sdist/wheel一致。新的 `/home/kenqia/issue69-review-base-venv` 与 `/home/kenqia/issue69-review-web-venv` 从固定 wheelhouse 离线安装，依赖检查通过，基础环境无 FastAPI/Uvicorn。仓库外 `python -I` 运行安装版十页完整往返及坏清单拒绝，基础环境 1.152 秒、web 环境 1.126 秒通过。脚本从公开矩阵提取同一行为检查，不导入仓库源码，日志为 `review69-packaging/{base,web}-ten-pages.log`。

未执行目标主机 systemd/cgroup、DNS/TLS 或公开部署；这些边界与 #74 原记录相同。
