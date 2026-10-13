# 项目工作约定

架构与支持范围读取 docs/architecture.md，验证入口和真实验收读取 docs/verification.md，领域术语见 GLOSSARY.md。项目文档使用 google-developer-docs 编写，unslop 润色。

默认入口为新版 convert.py prepare，调用 score_workflow.py。Agent 实际查看导航与原生截图、确认整曲来源、调用宿主生图、逐页审核后交付。操作读取 docs/agents/reconstruction-workflow.md，命令参数读取 docs/agents/reconstruction-entry.md。同位置重叠去重，后续重复音乐保留。水印与播放标记允许进入粗拼；音乐不可读时局部补采，不猜隐藏符号。

每个生成图页最多一次定向修正。生图缺失、失败或修正后仍不合格时使用轮廓转描与补五线的矢量兜底，不能称为音乐识别。选行保持完整谱行及关键记号；重排保持比例。原始来源与派生产物分开，实际 PTS、hash、调用记录、修正预算和来源验证须保留。旧 task/decision 协议、auto/fast/full、moving viewport、干净候选门禁与500行防火墙已退出，不自动迁移旧任务。

只有自然语言明确要求 MIDI 时加载 docs/agents/midi-conversion.md 与可选 Mido。可靠转写不满足时拒绝可靠输出；用户明确允许近似播放才执行授权分支，保留原未决转写和假设，标记 midi_playable、reliable=false。用户调整后的 #58 门槛见 docs/agents/reconstruction-acceptance-amendment.md；准确性限制不免除安全、完整曲长和实际回读。

运行仓库验证：

```sh
uv run --isolated --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt --with mido==1.3.3 python -m unittest discover -s tests -v
```

修改正常流程先运行针对性合成测试，再按变更风险验收真实来源和全部页面。#58保存 KiLLKiSS、BV1rH4y1R7Rk 与第三作者的实际证据，包含强制矢量与遮挡修复。记录实际 PTS、导航、原生保留和呈交数量、来源、修正、分页、保存决定恢复与耗时。未知成本保留 null。真实样本失败先检查 seek、几何、检测和原始内容，不新增样本颜色或 codec 例外。固定决定检查只证明确定性执行，不能冒充新的视觉判断。

匿名获取、网络公共地址校验、资源期限、解码清理、输出不覆盖和来源完整性保护不得随旧实现删除。只使用合成标记测试脱敏，不读真实凭证。GitHub Issues 位于 kenqia/bilibili-drum-score-to-pdf，远端读取核对 Git remote。写入按用户明确授权范围执行，不自动关闭工单或合并。历史实现与旧文档通过 Git history 查看。保护无关用户修改、实验及未跟踪规格。
