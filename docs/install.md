# 安装 Skill

安装保留完整提交快照。Skill 和脚本依赖仓库根目录的 `docs/agents` 协议，只复制 Skill 子目录会缺少这些文档。宿主需要读写本地文件、运行脚本、实际查看原生图像和渲染后的 PDF 页。跨宿主整曲交付的验证状态见 [首发准备记录](launch-readiness.md)。

## 准备源码

需要 Python 3.12+、Git、uv、ffmpeg、ffprobe 和 Poppler 的 pdftoppm。工具不修改模型认证，也不需要 B站 Cookie。

```sh
git clone https://github.com/kenqia/bilibili-drum-score-to-pdf.git
cd bilibili-drum-score-to-pdf
```

## 发现宿主与检查依赖

先运行不依赖第三方包的检查命令：

```sh
python skills/bilibili-drum-score-to-pdf/scripts/host_check.py
```

默认只检查 `~/.agents/skills`、`~/.codex/skills`、`~/.claude/skills` 的直接子目录 `SKILL.md`。宿主使用其他目录时传 `--skills-root /absolute/skills`，可重复指定。检查不读取宿主配置或凭证，也不修改安装。输出 JSON 包含匹配入口、同一根的重复入口、运行时工具、固定依赖版本和正常流程文档是否存在。文件存在不能证明宿主已经加载；实际工具清单和图片查看、生图能力仍须在宿主确认。

在实际隔离依赖环境中检查运行条件：

```sh
uv run --quiet --isolated --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt \
  python skills/bilibili-drum-score-to-pdf/scripts/host_check.py
```

安装副本使用根 `scripts/host_check.py` 和 `scripts/requirements.txt`。`--quiet` 减少依赖解析输出，命令失败时保留错误。依赖准备只运行一次检查，不反复编写探测脚本。扫描等待与进度见[程序检查](agents/automatic-source-checks.md#扫描预算进度与人工裁剪)。

## 安装或更新提交快照

停止使用目标安装的转换任务后，在源码仓库执行：

```sh
python tools/install_skill.py install --revision HEAD --target /absolute/host/skills/bilibili-drum-score-to-pdf
python tools/install_skill.py verify --target /absolute/host/skills/bilibili-drum-score-to-pdf
```

将目标换成宿主实际发现 Skill 的绝对目录，`--revision` 可指定完整提交。工具只读取 Git 提交快照，不复制工作区修改和未跟踪文件。安装保留完整提交中的文档与测试，复制规范脚本到根 `scripts`，调整根 `SKILL.md` 的示例路径。规范 Skill 文本保存为 `SKILL.source.md`，安装内只有根 `SKILL.md` 可被发现。开发时也可以直接注册源码仓库的 `skills/bilibili-drum-score-to-pdf`。

`installation.json` 记录源码提交、目标和全部受管理文件的 SHA-256。校验使用 64 KiB 流式读取。相同提交、文件清单和 hash 返回 `unchanged`，不替换安装；发现受管理文件改变时报告错误。新版本与未管理文件冲突时停止，不覆盖用户文件。

更新先完成快照校验，再将旧安装重命名到宿主 `skills` 目录外的同文件系统 `skill-backups`，迁移未管理任务目录后发布新目录。Python 捕获到发布失败时恢复旧安装和任务；不复制任务内容。更新期间不要并发启动转换或另一安装进程。进程被强制终止或机器断电无法运行恢复代码，目标缺失时从 `skill-backups` 找到旧目录，核对版本和任务位置，恢复到原目标后再继续。若恢复操作本身也遇到文件系统错误，工具保留带 `.recovery-required` 的 staging 目录；其中可能存有任务，恢复前不要删除。

## 验证安装

读取安装根 `SKILL.md` 和 `docs/agents/stage-recovery-layout.md`，在安装目录执行：

```sh
uv run --isolated --with-requirements scripts/requirements.txt python scripts/convert.py --help
uv run --isolated --with-requirements scripts/requirements.txt python ci/verify_agent_replay.py --output /absolute/new-install-smoke
```

将 smoke 输出换成一个新的目录。预期帮助包含 prepare、stage、重绘操作、export 和 review-pdf；合成集成 smoke 通过。每次同步执行全文件校验与这两个命令。源码变更先在 WSL 原生目录运行 [完整回归](verification.md)，安装副本不重复运行全套测试。

合成 smoke 不证明宿主生图、来源完整或实际页面审阅。首次宿主验收仍需使用支持范围内的视频，完成来源流程、真实宿主调用和全部页面检查。报告安装路径、源码提交、文件校验及 smoke 结果。

## 回滚

更新回执给出 `backup`。当前工具产生的备份可以这样回滚：

```sh
python tools/install_skill.py rollback --target /absolute/host/skills/bilibili-drum-score-to-pdf --backup /absolute/host/skill-backups/old-install
```

将备份换成回执中的实际路径。回滚同时保留当前版本备份和未管理任务。旧临时安装方案产生的备份可能含两个 `SKILL.md`，新校验会拒绝它；恢复该备份时把当前安装移到另一个备份目录，再将旧目录移回原目标，或按旧 `source_commit` 重新执行 `install`。确认任务恢复前保留全部备份。不同版本转换使用新任务和新结果目录，决定、耗时和成功记录分别保存。
