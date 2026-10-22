# 同仓库独立 Skill 与网站验证

2026-10-22，用户要求保留原仓库作为统一入口，main 同时提供独立 Skill 和网站，并提交 PR。实施分支 `codex/skill-and-website`，工作区 `/home/kenqia/issue69-unified-entry`。边界见 [ADR 0007](../adr/0007-independent-skill-and-website.md)。本轮不修改线上服务或已安装 Skill，不迁移任务，不合并 main 或关闭工单。

## 来源和改动

从已验收网站分支 `bbf7fb5f55dbad85e9cfcccfcda16c8e6f93a7e2` 建立分支。恢复远端 main `b4be2dc44427c3e0a7c741c7d1f81e23a41b6d2b` 的完整 Skill、安装工具、协议和合成重放。19 个 Skill 文件、两个安装/同步工具逐字一致；网站 25 个应用文件、pyproject 和四份部署模板与 bbf7fb5 逐字一致。

恢复的 Skill 依赖与 main 相同，包含自己的 yt-dlp；网站继续使用已验收 BBDownNext 2.3.0 有界构建直连，不把 yt-dlp 加入程序包。Skill 原测试复制到 `tests/skill/`，只调整新目录的仓库定位及专属 workflow 路径。根测试继续验证程序/网站。两套 workflow 独立安装依赖、发现测试并重放，job 名称区分产品。

新增回归将程序包单独复制到仓库外，实际完成合成视频转换，不带 Skill、工具或仓库 docs。另一项验证程序发现不载入 Skill 测试。Skill 原有 detached 测试继续验证复制包的 CLI、发现、协议和完整合成重放。

## 实际验证

证据根目录 `/home/kenqia/issue69-context/unified-entry-20261022`。

| 检查 | 本地结果 |
| --- | --- |
| Skill 完整回归 | 186 项，174.929 秒，通过；Linux 跳过两项 Windows 专属安装路径检查。`skill-full.log` |
| 程序与网站完整回归 | 171 项，126.861 秒，无跳过，通过。`web-full.log` |
| 独立发现与分片 | Skill 186 项分为93/93，程序171项分为86/85，分别无交集且并集等于各自完整发现。`discovery-partition.json` |
| 独立合成重放 | Skill 原图路线3行1页及矢量双跑/拒绝通过；程序3行1页双跑及拒绝通过。`skill-replay/summary.json`、`program-replay/summary.json` |
| Skill 真实提交安装 | 从 e126b3c 快照安装到全新实验宿主目录，19 文件核验、单入口与帮助命令通过；安装不含网站 src/pyproject/deploy/docs。`skill-install.json`、`skill-verify.json` |
| Python 分发 | 从 e126b3c 构建 sdist/wheel，25 包文件逐字等于源码和已部署 wheel；wheel/sdist 不含 Skill。`package-separation.json` |
| 仓库外基础安装 | 全新环境离线安装 wheel，pip check 通过；`python -I` 从安装包实际 API/CLI 转换3行1页、全部预览存在、PDF hash一致。`installed-program-smoke.json` |
| 依赖隔离 | Skill 环境无 drum_score/FastAPI/Uvicorn；网站环境无 yt-dlp；基础安装无 yt-dlp/FastAPI/Uvicorn。三个 pip check 均通过。`*-environment.json` |
| 规范与需求审阅 | 双轴各一项 P3，修复 Skill 文档失效锚点和重复 CI 检查名后复核未决0。`spec-recheck.md`、`standards-recheck.md` |
| 静态检查 | references同步、Ruff E701/E702、compileall、Markdown相对文件链接、workflow YAML及独立检查名、git diff --check通过。 |

构建 wheel SHA256 `97d5a9d4e58695ecf05f1db973b3b48d9fa34f231ab550866638d43a2d17bdab`。这是本轮仓库验证包，不替换服务器原发行。后续提交只修正文档与 CI 显示名，不改变25个应用文件或Skill包。

首次仓库外安装验收在 API/CLI 转换与 PDF hash 断言后，报告脚本误读不存在的 `page_count` 键而失败。只将脚本报告改为 `len(result['pages'])`，完整重跑通过，原脚本与失败说明保留；没有修改产品源码。

这些检查不代表新宿主已发现 Skill、Agent 实际看图、生图或音乐逐符号校对；本轮没有新的 B站下载、真实页面审阅或生产部署。Windows 专属检查由新 Skill CI 执行，本地 Linux 不冒称已验证。网站前轮公网实测见 [BBDownNext 接入记录](2026-10-22-bbdown-integration.md)。
