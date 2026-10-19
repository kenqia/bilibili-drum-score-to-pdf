# 安装与使用 Skill

对外发布目录是 `skills/bilibili-drum-score-to-pdf/`，包含 `SKILL.md`、`scripts/`、`references/` 和 `LICENSE`。运行协议已随包携带，安装时保留整个目录即可，无需复制源码仓库的 `docs/`、实验、测试或宣传素材。

## 安装后调用

在宿主输入框中选择 `bilibili-drum-score-to-pdf`，再提供视频链接。在 Codex 中可输入 `$` 选择 Skill。示例：

```text
$bilibili-drum-score-to-pdf
https://www.bilibili.com/video/BV1Yw4m1Y7YH/
```

Skill 默认处理 PDF。需要特定保存位置时，在同条消息补充路径。示例不构成该视频已通过验收的声明。其他宿主的选择方式依其界面而定。

## 首次安装

从仓库取得完整 Skill 目录，安装到当前宿主实际发现 Skill 的位置。可以让 Agent 按 README 中的安装提示完成，也可以使用宿主现有的 Skill 安装器。安装器必须同时复制 `scripts/`、`references/` 和许可证；只下载 SKILL.md 不完整。注册符号链接时，链接目标必须是保留所有内容的完整目录。

宿主需要文件读写、脚本运行、原生图片查看与 PDF 页面查看能力。环境需要 Python 3.12+、uv、ffmpeg、ffprobe 和 Poppler 的 pdftoppm。普通 PDF 不依赖 Mido。项目不要求 B站 Cookie，不读取模型认证。

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

## 使用仓库安装工具

需要可校验的提交版本、更新备份和任务保留时，在源码仓库执行：

```sh
git clone https://github.com/kenqia/bilibili-drum-score-to-pdf.git
cd bilibili-drum-score-to-pdf
python tools/install_skill.py install --revision HEAD --target /absolute/host/skills/bilibili-drum-score-to-pdf
python tools/install_skill.py verify --target /absolute/host/skills/bilibili-drum-score-to-pdf
```

将目标换成宿主实际发现 Skill 的绝对目录。工具从指定 Git 提交中只提取自包含 Skill，不复制工作区改动和未跟踪文件。`installation.json` 记录提交及所有受管理文件的 SHA-256，相同内容再次安装返回 `unchanged`；受管理文件损坏时拒绝更新。通用安装器复制的目录没有该清单时，先将原目录移到备份位置，再安装，不覆盖未知内容。

更新前停止使用目标安装的转换任务。工具在同一文件系统的 `skill-backups` 保留旧安装，迁移未管理任务目录后发布新版本。发现文件冲突时停止；发布失败时恢复旧安装与任务。旧完整仓库快照可升级，原材料保存在备份。机器断电或进程被强制终止时，从备份核对并恢复安装和任务位置；恢复失败保留带 `.recovery-required` 的暂存目录，检查任务前保留该目录。

## 验证安装

1. 在宿主技能列表或选择器中找到并选中本 Skill。若未发现，重新加载或重启宿主后检查。
2. 确认安装根的 `SKILL.md`、`scripts/convert.py` 和 `references/stage-recovery-layout.md` 可读；SKILL.md 的引用相对这个根目录。
3. 在安装目录执行下列命令，同时核对宿主看图能力与外部工具。

```sh
uv run --isolated --with-requirements scripts/requirements.txt python scripts/convert.py --help
ffmpeg -version
ffprobe -version
pdftoppm -v
```

帮助应包含 prepare、stage、export 和 review-pdf。能找到 Skill、能读取协议且命令成功，才说明安装入口可用。任务是否完成仍取决于真实来源、宿主调用与全部页面审阅，不把安装检查称为整曲验收。跨宿主状态见[首发记录](launch-readiness.md)。

## 回滚受管理安装

使用更新回执中的备份路径：

```sh
python tools/install_skill.py rollback --target /absolute/host/skills/bilibili-drum-score-to-pdf --backup /absolute/host/skill-backups/old-install
```

回滚保留当前版本备份和未管理任务。旧重复 SKILL.md 布局可能无法通过新校验，此时核对旧源码版本与任务位置后，恢复原备份或重新安装对应版本；确认全部任务恢复前保留备份。不同代码版本的转换使用新任务目录。

## 维护发布目录

仓库的 `docs/agents/` 是协议维护源；执行下面命令更新并检查随包引用。修改协议时同时提交生成的 references，避免已发布 Skill 与源码文档分离。

```sh
python tools/sync_skill_references.py
python tools/sync_skill_references.py --check
```

`tests/test_skill_package.py` 检查同步、包内链接、许可证，并把 Skill 单独复制到仓库外执行 CLI 和现有合成 PDF 验收流程。测试不调用模型、不证明音乐准确，也不证明宿主界面已发现安装。

## 匿名下载失败

安装检查通过只证明入口可用。获取失败时查看 `manifest.json` 的脱敏错误字段，区分代理 CONNECT 拒绝、来源 HTTP 拒绝与解码失败。程序只在 CONNECT403 或视频网页 HTTP412 时尝试一次公开 API 直连恢复；恢复会保留公共地址与 TLS 等保护，不持久修改代理配置。触发条件、来源完整性检查与资源限制见[输入和资源保护](architecture.md#输入和资源保护)。

已取得完整视频时可以用其本地路径继续 `prepare`，无需重新下载。视频应保存在任务相邻的独立来源目录，避免只保存在易清理的 `/tmp`。下载成功仍不代表谱行接续、重绘或全部 PDF 页面已验收。
