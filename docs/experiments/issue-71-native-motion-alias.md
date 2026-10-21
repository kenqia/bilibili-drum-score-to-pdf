# #71 原生时序检查修复周期采样丢段

2026-10-21。基于集成提交 `24de619`，独立工作区 `/home/kenqia/issue71-alias-fix`。本记录是公开合成输入验收，不是新真实谱面审阅或服务器验收。

## 故障与决定

七个完全相同、没有小节号的系统以30fps连续上移，每帧12像素。0.5秒采样恰好跨越一个180像素系统，两个采样图完全相同，但中间原生帧发生运动。旧实现把它当作停驻，返回完成和三个系统，原图实际有七个。

新增公开 `drum_score.convert` 回归先在旧实现运行，因没有抛出错误而失败。修复后返回 `discontinuity`，不发布部分结果，不改来源，清理私有暂存。程序没有足够依据确定完整位移时明确拒绝，不按周期猜测遗漏的系统数。

## 有界实现

仅共享核心启用 `VideoReader.sample_records(..., verify_motion=True)`。FFmpeg在选择保留帧前输出原生校验和观察，选择后输出实际PTS记录；独立线程并行读取stderr，每次最多4096字节，立即丢弃日志文本。原生观察只保留最近状态，采样PTS仍受4097条上限约束。不新增高频RGB持久化，也不改变原0.5秒采样、累计600秒解码预算、每次60秒解码期限、取消和进程清理。

同一采样校验和再次出现且其间发生变化时拒绝；原生序号、选中PTS或时间基记录不完整时也拒绝。原生校验和只证明发现过的变化，不能证明所有运动均可检测，也不能替代SHA-256完整性证据。整幅画面中的背景或播放标记变化后恢复可能触发保守拒绝，此限制已写入使用说明。完全静态输入继续通过。

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
