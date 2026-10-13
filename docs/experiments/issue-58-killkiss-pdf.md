# KiLLKiSS 的新鲜整曲 PDF 与未通过的 MIDI

2026-10-13，在实现 d832de4 上通过统一 URL 入口下载 BV15crrYUEPA。Agent 查看新帧，确认135小节、34个完整谱行，交付生图和强制矢量 PDF。最终各三页。首版失败材料保留；整曲 MIDI 未通过，不能关闭 Issue #58。

活动任务在 /home/kenqia/issue54-worktrees/killkiss/experiments/2026-10-13-issue58-recovered/killkiss/。task 和 forced-vector 保存来源、实际PTS、原帧、选行、输入、真实生图回执、版本化导出和看图记录。archive.json 列出产物 hash。源视频使用持久 worktree 的绝对路径；清理前需要保留引用文件。

Agent 根据新导航选取0、66、86、107、129、151、171、191秒，第80行半行缺口补采140秒，208.5秒确认结尾。独立复核发现86秒第31小节装饰音被水印遮住，于78秒补采完整第28行，实际PTS1248000，时间基准1/16000。正常重选和重新转描解决遮挡，没有重建缺失像素。

正式接口在选行变更后失效所有重绘页，因此重新执行三次真实宿主生图。新第一页两个开放镲0标记变成r/C，Agent拒绝并执行唯一一次定向修正。修正后实际查看0标记恢复。总计7次真实调用，旧版3次、新版3次、修正1次。initial-superseded-evidence.json 保存旧版回执与输出，未知模型成本null。

Agent 查看新最终六页，并查看31、67、75、134小节的原图、生图和矢量局部共12图。标题 KiLLKiSS、Ave Mujica、陈老师、速度200、4/4、休止10至11、三连音67、装饰音75、staccato134、短行100至101及结尾134至135保留。分页在完整行之间进行。生图新版第44行进入第二页，矢量版仍在第一页，没有固定旧页数。强制矢量新版 pdfimages -list 无位图项。

最终文件和 SHA-256：

- 生图 task/exports/d05a5357da4e40d7a1b3dc9353b904d8/KiLLKiSS.pdf，02edcd452f2d4fe25ff8d5b0ed5b747fc0938a909c3de8706b1e708de58232fd。
- 矢量 forced-vector/exports/ec04f9b4410946ccb770aa5395290de6/KiLLKiSS.pdf，6be673f66d0c169ad316c7b968fd2fcf84300b9c56949bd9ca33a9dbe998c286。

生图任务记录21次 seek、42帧解码器报告、11次低清探测、10张原生图。Agent实际查看10张导航和10张原生图，记录20次呈交。保存但未查看的第11张探测不计视觉分析。独立矢量记录10次 seek、20帧解码器报告、10张原生图和10次呈交。解码器报告帧数不等于实际视觉分析帧数。

原来源逐小节音乐候选保存135个 written measure IDs 和1410个候选 hit 事件，包含声部、分数拍点/时值、原源位置和休止，仍有55条复杂声部、符梁、附点或时长未决。无可核对作者鼓件图例，全部 GM note=null，保留原符号。midi_workflow 完整覆盖审阅提交后，实际 export_complete 拒绝 needs_music_review，PDF前后hash相同。候选数量不是可靠事件数量，也不是整曲 MIDI 成功交付。

root 新版独立复核结果另行记录，本文件未提前宣称通过。未修改生产实现，也没有为这份材料另跑合成测试。
