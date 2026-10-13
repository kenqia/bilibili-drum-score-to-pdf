# 验证记录

新版默认入口使用截图粗拼、宿主生图优先、轮廓矢量兜底与完整谱行 A4 重排。#58 在用户明确调整的验收要求下通过，#59 删除旧编排并切换入口。可靠整曲 MIDI 的原严格准确性门槛仍未通过，历史失败没有改写为成功。

## 离线验证

完整入口为以下命令。Mido 是独立可选依赖，此命令显式加入以验证 MIDI；普通 PDF 不需要它。

```sh
uv run --isolated --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt \
  --with mido==1.3.3 python -m unittest discover -s tests -v
```

新测试保留匿名网络、真实工作进程与信号期限、分 P、公共 DNS/TLS、签名 URL 脱敏、配置与认证哨兵、资源大小、原媒体尺寸、跨文件系统独占发布、用户目录保护、实际 PTS 和临时解码清理。默认入口检查新版任务、旧任务拒绝、恢复与 PDF-only 无 MIDI。重绘测试覆盖来源损坏、完整性、重叠与重复音乐、原生输出比例、一次修正、预算恢复、矢量路由、失败选择原子发布和最终 PDF 验证。MIDI 检查完整播放顺序、精确事件、读回、用户近似授权及路径边界。

CI 使用合成视频和保存的确定性选择检查矢量 PDF、A4 与来源拒绝，并另跑可选 MIDI 测试。它不调用宿主模型，不提供真实视觉或音乐准确证据。#59 实施 worktree 完整87项、43.578秒通过，日志 `/home/kenqia/issue54-recovery-evidence/issue59-full-final2.log`，包含可选 Mido。Python compileall、diff 检查和仓库外新版 help smoke 通过。最终 integration 冻结回归结果另行追加，实施 worktree 验证不冒充远端 CI。

## 三视频真实验收

用户要求修复 KiLLKiSS 第31小节遮挡后重新验收强制矢量 PDF，并接受“劣质一点也无所谓，能跑就行”的完整近似 MIDI。[验收调整](agents/reconstruction-acceptance-amendment.md)记录授权原话、产物和门槛。

三曲新鲜 PDF 为 KiLLKiSS BV15crrYUEPA、标准 BV1rH4y1R7Rk 与另一作者“小星星”BV1np421S78S，均保存来源、实际 PTS、完整谱行、宿主调用与每页实际审阅。标准和小星星分别两页、一页，KiLLKiSS 生图及强制矢量各三页。第31小节使用78秒实际PTS1248000的新完整原行修复装饰音遮挡；root 独立查看两路线全部六页和12张关键细节。矢量无位图，固定决定重放保持相同 PDF hash。

三曲近似 MIDI 由 root 独立 Mido 回读：小星星107事件、120拍、57600ticks；标准594事件、352拍、168960ticks；KiLLKiSS1409事件、540拍、259200ticks。均480PPQ、GM第10通道，完整曲长与 note-on/off 配对检查通过。输出标记 `midi_playable`、`reliable=false`，作者鼓件映射、节奏近似和播放约定如实保留。能解析和曲长正确不证明作者音乐等价。

实际记录见 docs/experiments/issue-58-standard-pdf.md、issue-58-other-pdf.md、issue-58-killkiss-independent-review.json 与 issue-58-playable-midi/summary.json。持久任务在 experiments/2026-10-13-issue58-recovered/。这些绝对任务位置只在本机可用，真实生图和每页看图不能用受控测试替代。未知模型成本为 null。

## 历史记录和限制

旧232项回归和2026-10-12首发10视频批次属于旧代码版本，结果通过 Git history 及保留的 release-test/data 查看。不能与新版测试数量合并。更早 /tmp 现场在环境重置后丢失，已保存档案仅证明历史产物，不宣称恢复或新看图。

当前只有 Codex 真实整曲记录，其他宿主没有整曲验收。仓库 Skill/CI 修改不代表宿主安装更新或远端 CI 通过。发布、工单关闭与 main 合并分别按用户授权执行。

## 最终集成结果

冻结提交 `c78bf48236a5127405ca36ed51e80755d246c4dd` 的完整带 Mido 回归为87项、34.875秒、无跳过，全部通过。两轴独立审阅无剩余发现。正式 CLI 重放三曲和强制矢量任务保留已验收 PDF，MIDI 恢复保留原记录；本次没有新的生图或视觉判断。独立 CI 合成矢量双跑相同，并通过四类拒绝检查。记录见 [#59 最终证据](experiments/issue-59-final/README.md)。
