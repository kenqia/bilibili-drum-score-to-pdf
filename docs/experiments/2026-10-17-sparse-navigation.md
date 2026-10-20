# 稀疏导航、谱行清单与鲜花实测

2026-10-17，本地分支 `codex/sparse-row-navigation` 从 GitHub main `7590af91f851e41711a2b281a802a89c020aabce` 实施三张工单。原有工作区的修改及历史任务保持原状。设计决定见[已确认规格](https://github.com/kenqia/bilibili-drum-score-to-pdf/blob/332922000d088803f4d74e8d7a4a7ebf93f26fc8/docs/agents/sparse-navigation-design.md)。没有新增运行依赖，没有更新宿主安装或执行远端写入。

## 实现与验证范围

默认 `stage` 先检查首尾布局，根据新增完整谱行和重叠调整跳转。未证实接续时回查区间，必要时局部连续扫描。导航缩略相似只用于找位置；原生细节不确定则交给 Agent，不自动批准音乐。`stage(mode="strict")` 保留连续扫描，扫描完成状态与谱行接续状态分别保存。

清单在采集过程中落盘，完整性未知时保存 provisional 来源与 unresolved 状态。稳定身份与显示顺序分开；同原谱位置保存备用来源，后续重复音乐保留新位置。最后选行关联原始 PTS、hash、裁剪及分组输入。元数据更新不会单独重置生图额度。新增 `row-manifest` 与 `review-continuity` 的 CLI/module 入口纳入公开契约矩阵。

十四项导航测试覆盖默认入口、首尾、严格切换、跳转调整和回查、无重叠编号、证据不足拒绝、编号冲突、不同位置相同音乐、补采身份稳定、恢复、清晰来源替换、人工选行撤回及原生 1×1 标题区域。严格扫描向已批准编号连接插入观察时，保留原材料并撤回完整资格，等待重新核对。旧扫描、缓存、来源安全、生图恢复及排版通过原回归验证。

Skill 和参考源同时更新，通过 `tools/sync_skill_references.py` 同步。保留局部恢复、未知调用、输入版本额度、矢量兜底和全部 PDF 页实际审阅要求。

## 同一真实来源的两种采集

样本为《鲜花》`BV1Yw4m1Y7YH`，复用本地原始 MP4，新建任务，不使用历史来源批准。原视频 335.32 秒、1920×1080、25 fps，SHA256 为 `9f948b7c4eca5c4e981baa2ca37563108393b37b1323b7008eafa8468b19947d`。本轮没有重新下载。

以下结果衡量不同覆盖范围，不能据此宣称同等完整度下的速度提升。

| 项目 | main 默认首轮 overview | 新默认导航及局部回查 |
| --- | --- | --- |
| 实际到达范围 | 0–63.56 秒 | 开头 0 秒，末端 335.28 秒，中间稀疏观察 |
| 解码报告帧数 | 1590 | 331，包含局部连续帧 |
| 其中连续观察帧数 | 1590 | 68 |
| 原生保留截图 | 128 | 150 |
| 原生保留字节 | 41,714,088 | 54,166,752 |
| 采集墙钟 | 29.152 秒，单次 overview 调用 | 178.667 秒，navigation 累计值 |
| 严格全曲覆盖 | false | false |
| 自动来源检查 | 首轮 pending，尚有后段未观察 | blocked，原生差异及裁剪等未决 |

旧 main 用尽 128 张候选预算，停止于 63.56 秒。新策略扩大了观察范围，但候选数量及保留字节没有减少，墙钟也不能证明更快。新策略发生 76 次跨度调整、55 次回查和 7 次局部连续扫描；程序需要更好的原生谱行匹配，才能进一步减少普通滚动视频的截图及人工核对。

另外运行旧 main 完整 `stage` 作诊断。它在前段重复局部检查，人工中止时记录为 346 张、15,985 连续帧、cursor 64.24 秒，未产生最终 stage 结果。此中止记录不计为完整扫描耗时，也不与完成的新导航作速度比。独立的首轮 overview 已正常返回，其结果用于上表。

原始导航决定、实际 PTS、来源 hash、最终选行和局部扫描区间保存在[鲜花元数据证据](2026-10-17-sparse-navigation/xianhua-evidence.json)。旧首轮记录见 [main overview 证据](2026-10-17-sparse-navigation/main-overview-evidence.json)。原始媒体和截图不复制进 Git。

## 失败、恢复与实际看图

前两轮校准任务 `xianhua-trial`、`xianhua-final` 因重复细节检查由主 Agent 中止，进度保留，不计为成功。第三轮 `xianhua-v3` 完成导航后，来源检查在 207.08 秒的一块原生 1×1 header 中触发 OpenCV 标量歧义。通过公开 CLI 反例复现，以同阈值的 NumPy 比较修复；没有丢弃标题、样本颜色或 codec 特例。公开 `stage` 恢复同任务，耗时 72.425 秒，返回来源 blocked。该耗时是恢复检查，不是重新采集导航。

恢复时程序保存 210 条暂定谱行及 257 条来源未决，不能当成 210 条有效音乐。主 Agent 实际查看四张整幅来源联系表、七张原生裁剪联系表和修正后的原生裁剪。读取行首小节号：

```text
1, 7, 11, 16, 20, 25, 29, 33, 37, 41, 45, 49, 53,
57, 61, 66, 70, 74, 78, 82, 86, 90, 94, 98, 102, 106, 110
```

实际修正了人工草选中 86、90 的来源索引，并把 11、61 行的第一及第二结尾记号归回相应行。通过公开 `present` 和 `assemble` 保存真实看图记录，选取标题块及 27 条完整谱行，对应印刷小节 1–113，保留后段重复音乐。开头检查标题、速度 100 和 4/4，结尾选择 110–113 行及终止双线；335.28 秒末端为黑屏，没有继续谱面。公开 `crop-checks` 返回 passed、issues=[]。新进程公开 CLI `row-manifest` 重新读取任务，返回 27 行且 continuity_complete=true，验证实际落盘后可恢复。谱行清单接续完整为 true，来源冻结 producer=agent，状态 `ready_to_redraw`。

这些是 Agent 对选中来源和音乐接续的判断，不是程序 OCR，也不证明未采样时间中没有短暂换页。严格时间覆盖仍为 false。没有进行新的宿主生图、矢量导出或最终 PDF 页面验收；保留这些阶段的现有能力不等于本次已完成真实交付。未知模型成本为 null。

本地任务和完整日志位于实施工作区的 `work/sparse-navigation/`：`xianhua-v3/record.json`、`real-v3.log`、`real-v3-recovered.log`、`source-review/assembled-review.json`、`main-overview.log` 及中止任务日志。Git 中的元数据副本足够检查导航决策和选行来源；它不替代本机原生图片的实际审阅。

## 独立审阅

Standards 初审发现同一实际来源可以写入矛盾编号范围。修复为保存前拒绝冲突，增加拒绝且记录不变的测试，复核通过。

Spec 初审发现原生像素去重可能吞掉已确认编号的新位置。修复为在去重前识别有效编号证据；复核又发现严格扫描新增观察时可能退回旧去重路径。最终实现保留已审核材料、返回 `numbered_anchor_requires_reconciliation`，要求 Agent 核对新增观察。测试覆盖原六行继续保留及完整资格撤回。提交 `bb1d759577cc8dd6286b195a3d63fb2e07243f73` 的复核无剩余发现。

两轴结论分别为 Standards 无剩余发现、Spec 无剩余发现。子 Agent 未独立运行测试；测试结果由主 Agent 记录。

## 最终验证

完整带 Mido 回归 179 项、167.647 秒、无失败、无跳过，全部通过，命令为：

```sh
uv run --quiet --isolated --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt --with mido==1.3.3 python -m unittest discover -s tests -v
```

日志保存在 `work/sparse-navigation/full-final.log`；命令、日志 hash 与检查摘要见 [验证回执](2026-10-17-sparse-navigation/verification.json)。`python -m compileall -q skills/bilibili-drum-score-to-pdf/scripts tests`、Ruff 0.14.14 的 E701/E702、`python tools/sync_skill_references.py --check` 及 `git diff --check` 通过。仓库未配置静态类型检查；compileall 仅检查语法，不替代类型检查。真实解码任务均结束后才运行完整回归。

本轮交付是本地代码、测试、Skill 与实测记录。未执行远端 CI、push、PR 或 main 合并。
