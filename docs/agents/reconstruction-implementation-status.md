# Issue #54 实施记录

截至 2026-10-13，#55、#56、#57 的软件增量已合入 `codex/issue-54-integration`。#58 完成三视频 PDF、第31小节修复后的真实强制矢量及用户授权的近似整曲 MIDI 验收。#59 在独立 worktree 删除旧流程并切换新版默认入口，等待最终集成回归与独立审阅。原可靠音乐准确性门槛仍未通过，不能将近似 MIDI 称为可靠。

## 工作区和任务图

Git 基线为 `51aa468e1cab45010355100244a647ef3b8945e7`，任务图为 #55 → #56 → #57 → #58 → #59。初始工作区已有 `GLOSSARY.md`、`docs/agents/issue-tracker.md` 修改，以及规格、ADR、研究、实验、`.scratch/` 和 `.archify/` 等未跟踪材料。实施没有覆盖或批量提交这些文件。基线与五份保护文件 hash 副本保存在 `experiments/2026-10-13-issue54-local/baseline.json`。

运行环境中途重置，原 `/tmp`、运行中的测试和旧 Agent 丢失。Git 提交、工作区与已保存档案保留。旧临时任务不能称作可恢复；档案中的原路径是历史来源。新鲜验收使用 `experiments/2026-10-13-issue58-recovered/` 和 `/home/kenqia/issue54-worktrees/`，日志使用 `/home/kenqia/issue54-recovery-evidence/`。

## 已实现的软件

#55 的 `reconstruction.py` 保存实际 PTS、来源 hash、完整选行和粗拼，执行轮廓转描与补五线，按完整行等比分页，单独记录实际 PDF 审阅。独立版本目录保留旧 PDF 和用户文件，支持重新选行及中断恢复。粗拼按像素内存预算分块。详见[本地重构工作流](reconstruction-local.md)。

#55 十五小节音乐比较实际执行两条候选。Agent 加 Mido 在声明的实验映射下回读 141 次击打和 60 拍；Audiveris 加 MuseScore 的有限交换修正仅有 77/141 次击打的鼓件和起拍一致。未知镲映射没有放行。#55 明确允许记录没有可靠候选，不阻塞 PDF 增量，但不能替代真实整曲 MIDI。见[候选比较](../experiments/issue-55-midi/README.md)。

#56 的 `score_workflow.py` 提供统一匿名 URL/本地来源、低清导航、原生取帧、呈交记录、原位置去重、真实宿主生图交接、每页一次修正与矢量兜底。原生生成图按来源宽度归一化重排，无新增位图重采样。相同材料恢复保留输出和修正次数；变更选行原子失效旧生成材料；最终 PDF 审阅核验完整来源。见[新工作流](reconstruction-workflow.md)。

#57 的可选 `midi_workflow.py` 与 `midi_export.py` 将完整音乐审阅绑定到 PDF、原图和转写 hash。自然语言明确请求后才启动；全部小节和播放顺序必须覆盖，未知项拒绝导出并保留 PDF。导出使用 GM 第 10 通道、精确 480 PPQ、实际事件回读，路径限制在任务内。完整受控三小节谱经实际查看后展开为五小节、26 次击打和 18 拍，包含三连音、装饰音、反复、力度、变速与变拍号。见[受控整谱验收](../experiments/issue-57-midi/README.md)。受控谱不能替代三条真实样本。

后续审阅增加显式 `reject_accepted_redraw()`，保留旧图、PDF、审阅和预算，撤回当前交付引用；预算耗尽时转矢量。另修复小节内明确变速遗漏，`measure.tempo_changes` 使用精确局部拍点，随反复重放并接续下一小节初速。非法结构、区间、顺序、BPM 和不能精确表示的拍点在提交时拒绝。集成提交分别为 `383df669` 和 `e5da0f65`。

## 新鲜验证

在 `d832de4` 上重新执行仓库完整命令，共 269 项、954.108 秒，255 项通过、14 项因可选 Mido 缺失跳过，退出码 0。日志为 `full-unittest-retry.log`。更早的基线完整回归有一次 ffmpeg SIGKILL；目标单项后来通过，不把原失败改记为通过。其他中断运行不计为完成。

后续两项修复合并后按影响范围验证。`e5da0f65` 上 workflow 13 项通过、3.197 秒，日志为 `final-score-workflow.log`。可选 MIDI 使用隔离 requirements 加 Mido 1.3.3，17 项通过、0.129 秒，日志为 `tempo-merge-green.log`。两项修复没有重跑完整套件；旧提交的完整结果不标为当前提交的完整回归。

```sh
uv run --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt python -m unittest discover -s tests -v
uv run --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt python -m unittest discover -s tests -p 'test_score_workflow.py' -v
uv run --isolated --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt --with mido==1.3.3 python -m unittest discover -s tests -p 'test_midi*.py' -v
```

独立 Standards 审阅在冻结提交 `383df669` 上无发现；Spec 审阅发现小节内变速遗漏，修复后独立复核无新发现。审阅记录位于持久日志目录。

## 实际样本和发布门槛

标准 BV1rH4y1R7Rk 新鲜匿名获取后，实际查看 5 张原生图和 6 张导航图，两次真实宿主生图、零修正，完整 1 至 88 小节输出两页 PDF。root 与 implementer 独立查看页面，并放大核对第 59 小节脚踩叉形符头和第 87 小节镲附点。两处均保留，root 的缩图疑点已撤回。见[标准 PDF 验收](../experiments/issue-58-standard-pdf.md)。整曲 MIDI 未验收。

第三作者 BV1np421S78S 实际查看 1 张原生图与 3 张导航图，一次真实宿主生图、零修正，完整 16 小节输出一页“小星星.pdf”。两位 Agent 独立查看原图与最终 PDF 后接受。完整音乐转写记录 58 次写定击打，反复后为 107 次、120 拍；作者鼓件映射及 rit 播放约定未决。实际 MIDI 导出拒绝，PDF hash 不变。见[第三作者验收](../experiments/issue-58-other-pdf.md)。

KiLLKiSS BV15crrYUEPA 的新鲜三页生图和三页强制矢量产物已实际查看。矢量第 31 小节装饰音受到源水印遮挡，正在针对该行补采和重新导出；旧版本不计为矢量通过。整曲音乐验收未完成。新记录保存在持久 killkiss worktree，不以原型或片段替代整曲验收。

未知模型及完整宿主成本保持 `null`。没有 push、PR、远端合并、Issue 修改或发布。


## #59 默认切换与清理

新版 `convert.py` 默认 prepare 调用 `score_workflow.py`，提供轻量操作与参数 JSON 适配，不执行宿主模型。旧 convert、auto/fast/full、旧任务和决定兼容层退出，旧任务不自动迁移。删除31个旧脚本、旧专属测试与17份活跃旧协议文档；保留匿名获取三模块、实际 PTS 解码、谱名安全及新重构与 MIDI 模块。旧历史验收、原实验、用户规格和无关文件保留。

获取和生命周期测试迁到新版 CLI，保留公共 DNS/TLS、匿名配置哨兵、脱敏、真实 SIGTERM/期限、跨文件系统发布、大小及实测尺寸保护。URL/local 来源相同、实际 PTS、临时目录与文件名测试单独保留。新版 CI 使用合成确定性矢量产物和可选 MIDI job，不计真实生图或看图。

选行不变但完整性疑点后来解除时，恢复 ready_to_redraw 状态；受控公共接口测试先失败后通过。正式 Skill、README、项目约定、架构、验证、安装和首发说明改写为当前流程，保留近似 MIDI 授权要求和 reliable=false。具体冻结测试与集成结果由最终收口追加。
