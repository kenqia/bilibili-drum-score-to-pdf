# 项目工作约定

架构与支持范围读取 docs/architecture.md，验证入口和真实验收读取 docs/verification.md，领域术语见 GLOSSARY.md。项目文档使用 google-developer-docs 编写，unslop 润色。

正常 PDF 任务准备后使用 `stage`，先读取 docs/agents/stage-recovery-layout.md；命令参数读取 docs/agents/reconstruction-entry.md。来源检查未决或需人工恢复时读取 docs/agents/automatic-source-checks.md 和 docs/agents/reconstruction-workflow.md。同位置重叠去重，后续重复音乐保留。水印与播放标记允许进入粗拼；音乐不可读时局部补采，不猜隐藏符号。

生成调用、按输入版本计的修正预算、未知调用恢复和矢量兜底遵循 docs/agents/stage-recovery-layout.md。轮廓转描不能称为音乐识别。选行保持完整谱行及关键记号，重排保持比例；原始来源与派生产物分开，保留实际 PTS、hash、调用记录和来源验证。历史实现通过 Git history 查看，不自动迁移旧任务。

只有自然语言明确要求 MIDI 时加载 docs/agents/midi-conversion.md 与可选 Mido。可靠转写不满足时拒绝可靠输出；用户明确允许近似播放才执行授权分支，保留原未决转写和假设，标记 midi_playable、reliable=false。用户调整后的 #58 门槛见 docs/agents/reconstruction-acceptance-amendment.md；准确性限制不免除安全、完整曲长和实际回读。

运行仓库验证：

```sh
uv run --isolated --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt --with mido==1.3.3 python -m unittest discover -s tests -v
```

修改正常流程先运行针对性合成测试，再按变更风险验收真实来源和全部页面。#58保存 KiLLKiSS、BV1rH4y1R7Rk 与第三作者的实际证据，包含强制矢量与遮挡修复。记录实际 PTS、导航、原生保留和呈交数量、来源、修正、分页、保存决定恢复与耗时。未知成本保留 null。真实样本失败先检查 seek、几何、检测和原始内容，不新增样本颜色或 codec 例外。固定决定检查只证明确定性执行，不能冒充新的视觉判断。

匿名获取、网络公共地址校验、资源期限、解码清理、输出不覆盖和来源完整性保护不得随旧实现删除。只使用合成标记测试脱敏，不读真实凭证。GitHub Issues 位于 kenqia/bilibili-drum-score-to-pdf，远端读取核对 Git remote。写入按用户明确授权范围执行，不自动关闭工单或合并。历史实现与旧文档通过 Git history 查看。保护无关用户修改、实验及未跟踪规格。

对外 Skill 为 `skills/bilibili-drum-score-to-pdf/` 自包含目录，运行协议位于随包的 `references/`。修改 `docs/agents/` 协议后运行 `python tools/sync_skill_references.py`，提交生成材料；`--check` 与 `tests/test_skill_package.py` 验证同步和仓库外运行。保留现有安装保护与任务备份，不将开发测试、实验或宣传素材加入安装包。

跨轮次或压缩后的工程续跑先读取当前工作交接的 CURRENT.md，再核对 Git；更新方法见 docs/agents/engineering-handoff.md。公开入口变更须加入 tests/test_public_contracts.py 的共同约束矩阵，验证与审阅规则见 docs/verification.md。
