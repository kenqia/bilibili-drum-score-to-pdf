# #71 原生时序检查修复周期采样丢段

2026-10-21。基于集成提交 `24de619`，独立工作区 `/home/kenqia/issue71-alias-fix`。本记录是公开合成输入验收，不是新真实谱面审阅或服务器验收。

## 故障与决定

七个完全相同、没有小节号的系统以30fps连续上移，每帧12像素。0.5秒采样恰好跨越一个180像素系统，两个采样图完全相同，但中间原生帧发生运动。旧实现把它当作停驻，返回完成和三个系统，原图实际有七个。

新增公开 `drum_score.convert` 回归先在旧实现运行，因没有抛出错误而失败。修复后返回 `discontinuity`，不发布部分结果，不改来源，清理私有暂存。程序没有足够依据确定完整位移时明确拒绝，不按周期猜测遗漏的系统数。

## 后续有损输入复核

`1cd0377` 的精确校验和方案仍有缺口。同一76帧输入转为libx264 CRF23、yuv420p后，公开转换仍完成并仅输出三个系统；新增静态H264输入又被精确校验和变化误拒。两项公开回归在修复前分别出现失败和错误，日志为 `/home/kenqia/issue69-context/alias71-lossy-red.log`。这是实际反例，不因编码不同而例外放行。

## 当前有界实现

仅共享核心启用 `VideoReader.sample_records(..., verify_motion=True)`。FFmpeg在同一次解码中split：原始RGB取样支路保持不变；运动支路将每个原生帧等比缩至最大128×128，转为8位亮度统计，通过signalstats输出相邻原生帧的亮度平均绝对差。没有新增seek，过滤线程限制为1。独立线程并行读取stderr，每次最多4096字节，立即丢弃日志文本。逐帧序号、PTS和统计必须完整配对；采样PTS和每间隔最大差值最多4097条，原生中间状态只有常数个。

配准近零位移不超过2像素，而间隔最大原生亮度差超过1时，返回 `discontinuity`。全画面缩图和阈值用于区分显著变化与微小编码抖动，不依赖exact checksum、另一固定采样率或编码例外。程序不按周期猜测遗漏的系统数。空白或片头观察被跳过时，仍汇总两次实际谱面之间的运动证据；末尾实际读帧使用剩余尾段摘要。

128像素缩图、亮度差1和近零位移2像素都是启发式边界，不保证检测全部运动。背景或播放标记变化可能导致保守拒绝，小运动可能漏检。运动观察不是SHA-256来源完整性证据。保持0.5秒取样、累计600秒解码预算、每次60秒解码期限、任务资源监督、取消和进程清理。不声称新增检查的真实性能已通过四曲或服务器验证。

## 本地验证

在已有独立Python 3.12虚拟环境中运行，未安装依赖，未修改全局环境。命令为：

```sh
PATH=/home/kenqia/bilibili-ci-python312-venv/bin:$PATH \
PYTHONPATH=src:skills/bilibili-drum-score-to-pdf/scripts:tests \
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
/home/kenqia/bilibili-ci-python312-venv/bin/python -m unittest \
  test_script_conversion test_media_boundary -v
```

21项通过，12.651秒。包含本次无编号周期混叠拒绝、带小节号快滚完整七行、慢滚重复七行、静态图和PDF逐像素保留、彩色关联记号、实际PTS、原始来源不覆盖、总期限、取消、SIGKILL后子进程与暂存清理，以及原长图调用方回归。日志在 `/home/kenqia/issue69-context/alias71-targeted-fixed-env.log`。

首次专项21项中一项未创建fixture的decoder-pid，原日志保留为 `alias71-targeted.log`。原因是直接调用3.12解释器却未前置其bin目录，fixture的 `#!/usr/bin/env python3` 选择了Miniconda解释器，同时继承3.12标准库路径，发生 `SRE module mismatch`。修正本次命令PATH后全部通过；未修改fixture、期限或断言。

`compileall` 与 `git diff --check` 通过。集成后的全量回归、四曲和连续三任务由主任务在最终版本重新运行；本记录不把旧版本的真实结果当作本修复验证。

## 有损修复验证

同一公开周期样本同时以FFV1和libx264 CRF23、yuv420p运行，都明确拒绝；静态H264与原无损静态都完成，未额外扩展谱面。首次三项GREEN为4.711秒，日志 `alias71-lossy-green.log`。扩展专项22项、17.356秒全部通过，日志 `alias71-lossy-targeted.log`。后续补充过滤线程限制与跨空白间隔汇总后，最终专项另行记录。未执行完整回归；主任务合并后验证最终四曲、全部页面、连续三任务和全回归。

### 非零周期别名与最终专项

继续将每原生帧位移改为18像素，使每采样位移为270像素。只判断近零冲突的中间实现仍把它折成90像素位移，两种编码的公开回归均失败，日志为 `alias71-wide-red.log`。

最终配准在有显著原生变化、且稀疏采样跳过了实际中间帧时，拒绝全局及局部匹配质量同等、位置相隔超过2像素的候选，不依赖 `prefer=0` 选择小周期。取样已包含每个原生帧的既有慢滚保留原相邻配准。该区别依据实际原生观察是否被跳过，不检查具体codec、颜色或固定帧率；不能据此宣称能恢复原始视频从未记录的帧间运动。

最终同一公开用例覆盖12和18像素原生步进，各自FFV1与H264共四个拒绝分支。编号快滚完整七行、无编号慢滚完整七行、静态H264、无损静态、彩色关联记号及所有原进程/期限保护通过。22项、18.065秒，日志 `/home/kenqia/issue69-context/alias71-wide-final-targeted.log`。`compileall` 与 `git diff --check` 通过。最终真实四曲、全回归及独立复核仍由集成任务执行。

## 实际解码尾PTS回退修复

集成 `99847ee` 最终固定集的《鲜花》在31.073秒返回 `decode_failed`，未发布结果。原失败保留在 `/home/kenqia/issue69-context/evidence/motion-final/xianhua/`，不改写为成功。最小诊断使用相同FFmpeg图，只保留首个不匹配元数据与计数，不保存完整stderr。结果为8383条原生header和统计、645条采样，FFmpeg正常退出；唯一首错是最后原生PTS由5364480回退到5363840。独立ffprobe末帧也为335.28秒后335.24秒，说明是实际解码顺序中的尾部PTS回退，不是记录缺失、资源不足或配准阈值。

新增公开回归通过真实FFmpeg生成两秒静态MP4，然后只修改合成MP4的ctts末帧presentation offset。ffprobe实际确认尾PTS回退，旧代码的公开转换出现同样错误。最小修复移除不成立的原生PTS单调要求，继续严格验证原生序号、逐帧header/统计与选中PTS配对，不对帧排序、不伪造PTS。回归还检查转换成功、三行保留、原生观察数量、尾部实际PTS和来源不变。

23项专项19.276秒全部通过，日志为 `/home/kenqia/issue69-context/native71-pts-targeted.log`。公开RED日志 `native71-pts-red.log` 与实际源诊断摘要 `diagnose-motion-pairing.json` 均保留。固定源公开重跑及桌面PDF哈希比较另记于下文；未执行全量或其他三曲。

### 唯一位置与背景变化误拒

删除错误的PTS单调要求后，实际《鲜花》重跑越过记录检查，但在67.6秒、采样index130被旧近零保护拒绝。诊断只保存首个冲突元数据：亮度平均绝对差最大1.02214，唯一可行候选为约0像素、全局代价0.04598；其他候选全局代价至少0.4348，均不合格。原失败日志为 `native71-pts-xianhua.log`，诊断为 `diagnose-xianhua-registration.jsonl`。这不是位置歧义，而是把全画面变化直接当成滚动。

新增公开合成视频在独特静态谱面外的背景区域切换亮块，产生明显原生变化，但谱面只有唯一零位移。旧实现公开转换失败，保留RED日志 `native71-background-red.log`。修复删除“显著变化加近零就拒绝”的独立条件，改为有实际中间变化时要求所有候选可区分；相同采样也必须搜索候选，多个等价位置仍拒绝。没有按来源、codec或颜色放行。原先记录中的近零阈值描述属于被此修复替代的中间实现。

### 本次最终验证

最小修复后的24项专项24.826秒通过，日志为 `/home/kenqia/issue69-context/native71-pts-background-targeted.log`；包含尾PTS回退和动态背景的新鲜公开RED→GREEN、四种周期别名拒绝，以及原静态、慢滚、编号快滚、PTS、期限和真实进程清理。

随后串行通过公开 `convert` 重跑既有《鲜花》固定源，126.257秒完成三页。PDF SHA-256为 `5e4d47d7e3efc611ccd8985de56230c69a945937cc1145320fe527cd5cd4370c`，与 `resource-balanced-final` 及桌面放大均衡版的 `鲜花.pdf` 完全一致。源hash未变，8383次原生观察，末尾实际PTS仍为5363840、time_base为1/16000、335.24秒；没有把它重写成335.28秒。解码累计31.260秒、两次seek；采样树RSS峰值243736576字节、观察到的任务暂存峰值263257074字节，均为本机采样值，不是cgroup硬峰值。任务暂存已清理。

报告在 `/home/kenqia/issue69-context/evidence/native-pts-xianhua-v2/report.json`，日志为 `native71-pts-xianhua-v2.log`。PDF相同证明与已交付版本一致，不代表本轮逐符号音乐校对或新的视觉判断。`compileall` 与 `git diff --check` 通过。未运行完整回归、其他三曲或服务器验收，主任务将按最终集成版本复跑。
