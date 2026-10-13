# 安装 Skill

安装时保留完整仓库。`skills/bilibili-drum-score-to-pdf/SKILL.md` 和脚本依赖仓库根目录的 `docs/agents` 协议；只复制 Skill 子目录会缺少这些文档。

## 交给 Agent 安装

将下面这段话交给你正在使用的视觉 Agent。

```text
请从 https://github.com/kenqia/bilibili-drum-score-to-pdf 安装
bilibili-drum-score-to-pdf Skill。

保留完整仓库，按当前宿主的 Skill 安装约定注册
skills/bilibili-drum-score-to-pdf 目录。
通过 SKILL.md 的真实路径定位仓库根目录，确认 docs/agents 可读。
检查 Python 3.12+、uv、ffmpeg、ffprobe，以及查看原生 PNG 的能力。
逐页 PDF 审核需要渲染工具，本项目使用 Poppler 的 pdftoppm。
报告安装路径、源码版本和检查结果。更新已有安装时先保留可恢复副本。
```

宿主需要读写本地文件、运行脚本、实际查看原生图像和渲染后的 PDF 页。注册位置与发现方式取决于宿主；可读 Markdown 不等于能完成整个工作流。跨宿主整曲交付的验证状态见 [首发准备记录](launch-readiness.md)。

## 手动保留仓库

先将仓库保存到你选定的持久目录。

```sh
git clone https://github.com/kenqia/bilibili-drum-score-to-pdf.git
cd bilibili-drum-score-to-pdf
uv run --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt \
  python skills/bilibili-drum-score-to-pdf/scripts/convert.py --help
```

将该仓库里的 Skill 目录注册到宿主，不移动或删除根目录的协议文档。若宿主支持目录符号链接，链接到这个持久仓库中的 Skill 目录；若宿主只支持复制，保留完整仓库副本并让 Agent 明确协议根路径。此项目不修改模型认证，也不需要 B站 Cookie。

## 验证安装

让 Agent 读取已注册的 SKILL.md、仓库的 `docs/agents/reconstruction-workflow.md` 和 `docs/agents/reconstruction-entry.md`，执行 `convert.py --help`。预期输出包含 prepare、capture、assemble、重绘操作、export 与 review-pdf，默认使用新版 prepare。旧模式和决定兼容层不再提供。随后使用一个属于支持范围的视频，实际完成原图审阅和逐页 PDF 检查；帮助命令成功只证明脚本入口可用。

更新时记录原源码版本，并保留已有任务与产物。需要回滚时恢复原安装副本，转换使用新任务和新结果目录。不同版本的决定、耗时与成功记录分开保存。
