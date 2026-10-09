# B站动态鼓谱转 PDF

输入 B站 BV 链接或本地视频，由 Agent 查看视频中已有的白底多行鼓谱，确定谱行身份、完整性和干净来源。脚本核对几何、实际 PTS 与单帧裁剪，再生成 A4 纵向 PDF。

## 运行

需要 Python 3.12+、uv、ffmpeg 和 ffprobe。uv 使用独立环境运行仓库已声明的依赖，无需登录 B站或配置 Cookie。

```sh
uv run --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt skills/bilibili-drum-score-to-pdf/scripts/convert.py 'https://www.bilibili.com/video/BV1rH4y1R7Rk' --output /absolute/new-task
uv run --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt skills/bilibili-drum-score-to-pdf/scripts/convert.py /absolute/video.mp4 --output /absolute/new-task
```

默认操作是 prepare，返回 `waiting` 并保存观察包，不直接生成 PDF。Agent 实际阅读原帧、相邻对照图和所选原生细节，记录身份、完整性、遮挡与首尾；必要时补采样。Agent 写决定并提交，用户无需填写 JSON。字段和补采、分批审阅、恢复操作见 [Agent workflow](docs/agents/agent-workflow.md)。

```sh
uv run --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt skills/bilibili-drum-score-to-pdf/scripts/convert.py --operation submit --task /absolute/new-task --decision /absolute/agent-decision.json
uv run --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt skills/bilibili-drum-score-to-pdf/scripts/convert.py --operation export --task /absolute/new-task --output /absolute/new-result
uv run --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt skills/bilibili-drum-score-to-pdf/scripts/convert.py --operation replay --task /absolute/new-task --output /absolute/new-replay
```

任务与结果使用不同的新空目录。检查 stdout JSON 和 manifest.json。只有 `success`、`complete=true` 且没有未决区间时才交付完整曲谱。`waiting` 保留证据与疑点，可 resume 或按协议补采；`failed` 给出脱敏诊断。匿名获取失败且目录仅含失败 manifest 时，可用原命令重试。

结果包含 score.pdf、显式标题或行外区域、逐行 RGB 原裁剪与灰度打印图、原视频帧和来源记录。每行可按 timestamp、bbox 与 original_image 核对。打印前逐页检查标题、速度、拍号、细小记号与首尾。

## 支持范围

固定谱面可用 v1/v2，固定比例、白底、多行、单向向上推进的连续长谱使用 v3 或 v4 的段内协议，相邻窗口至少两条完整谱行可靠重叠。有序翻页用 v4，须从实际原图确认末小节与下一页首小节接续，空间段分别编号。重复段落按原谱空间位置保留；半行等到完整出现才收录。

每条打印谱行来自一张真实完整原帧，只转灰度。Agent 判断光标、复杂遮挡、细小符号与边界；脚本验证坐标、来源和几何，不重画、修补或拼接音符。没有可确认的干净完整观察时等待。源视频中的彩色静态记号原样保留，不能据颜色断言其作者或应用来源。

低于 150 effective DPI 的谱行拒绝打印。高 DPI 仍需实际核对清晰度。比例变化、倒退、无重叠的大跳跃、未知遮挡与无法确认的翻页关系可能等待。稀疏采样不能证明未采样时间没有换谱，重放也不能证明模型识别正确。

## 验证与回滚

```sh
uv run --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt python -m unittest discover -s tests -v
```

测试还需要 Poppler 的 pdfinfo、pdfimages 与 pdftoppm。GitHub Actions 运行全部离线回归与固定 Agent 决策重放。受控证据见 [离线 CI](docs/agents/offline-ci.md)，双份真实视觉审阅、独立来源核对与成本边界见 [verification](docs/verification.md)。架构、资源限额与安全边界见 [architecture](docs/architecture.md)。随仓库交付的 [SKILL.md](skills/bilibili-drum-score-to-pdf/SKILL.md) 使用同一默认流程。

保留的 moving viewport 路径用 `--operation convert` 显式运行。三个核心模块合计不得超过 500 行，依赖防火墙继续约束它。需要回滚完整产品时，在独立 checkout 使用旧稳定提交 `23ec65459807bed7a51f3fa0f1e9c08b51cc63dc` 和新的结果目录；保留已有 Agent 任务，不迁移或覆盖其记录。

授权宿主的真实 Token、工具与图像呈交可用 [计量适配器](docs/agents/host-usage.md) 采集和导入，汇总按真实审阅、重放与入口分别统计。缺失模型调用或呈交覆盖时保留 null，不将开发会话成本当作视频基线。


## 显式实验入口

在隔离的 `codex/issue-43-software-experiment` 分支，`prepare --evidence-mode lazy` 保留原帧和导航对照图，按 Agent 的原生 ROI 请求生成细节。`materialize` 保存来源与证据更新，`build-decision` 根据几何建议、修正和实际确认构建现有协议的决定。操作字段见 [惰性证据](docs/agents/lazy-evidence.md) 与 [决定构建](docs/agents/decision-building.md)。默认 full/prepare 与旧任务重放继续保留。

`review-plan` 按疑点给出相邻实际 PTS、原生 ROI 和有界补采请求，输出尚未确认的构建模板。物化后需要沿用未改的实际判断时，使用显式历史复用，规则见 [疑点审阅](docs/agents/review-plan.md)。lazy 的局部内容检查可否决几何自洽的错误对应；污染必需接续帧时，当前不能仅靠新增干净帧解除等待，具体范围见 [内容检查](docs/agents/content-checks.md)。

lazy 提交使用 v4 原生图块，并附绑定决定文件的 `audit.json`。标题、速度、拍号、行外区域、首尾与各相邻间隔都须显式核查，缺少证据时等待。字段与导航限额后的有界恢复见 [覆盖审计](docs/agents/coverage-audit.md)。

实验能力仍要求实际原图和原生细节审阅。合成验证不代表真实视频质量或端到端性能放行；完整真实成本未知时保持 null。自动接受和默认快路径尚未启用。使用新任务、草稿与结果目录，保留来源和接受历史；回退到冻结的 `d09fa9d` 使用另一独立目录。
