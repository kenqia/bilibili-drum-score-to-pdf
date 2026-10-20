# Agent-first 跨宿主修复验证

本轮从 main `9cece50dcfe78affd6f8739c3221521d8bdbf55d` 实施。用户接受全部采访决定，并负责真实视频和跨宿主验收。实施规格见 [Agent-first 修复规格](https://github.com/kenqia/bilibili-drum-score-to-pdf/blob/332922000d088803f4d74e8d7a4a7ebf93f26fc8/docs/agents/agent-first-cross-host-spec.md)，实际验收步骤见 [用户验收清单](https://github.com/kenqia/bilibili-drum-score-to-pdf/blob/332922000d088803f4d74e8d7a4a7ebf93f26fc8/docs/agents/agent-first-cross-host-acceptance.md)。

## 变更与证据边界

默认 stage 返回 Agent 来源任务，不启动自动扫描。来源批准要求实际呈交、来源绑定的结构化证据和已有疑点逐项处理。共享任务入口统一执行门禁，合法旧人工冻结只继承未变来源、接续及同角色的标题和首尾批准。改动位置、裁剪或首尾角色需要新证据。显式 sparse/strict 仍使用各自原检查与覆盖声明。

本轮同时修复混合缺号接续、UTF-8 与 POSIX 安装清单、FFmpeg 能力兼容、宿主检查不中止发现、稳定错误分类、局部修订及摘要回执。Windows CI 新增原生重点套件，没有执行远端写入或更新共享 Skill。

所有新增测试使用合成视频、图像与受控审阅声明。测试中的 present、evidence 和 PDF review 只验证状态与引用约束，不能证明真实 Agent 看图或整曲音乐完整。本轮没有真实生图调用，未知成本为 null。

## 本地验证

完整回归使用仓库既有入口，固定 Python 3.12 并带可选 Mido：

```sh
uv run --python 3.12 --isolated \
  --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt \
  --with mido==1.3.3 python -m unittest discover -s tests -v
```

- 基线复现：夹杂 start_bar=None 的接续在原源码触发 TypeError；修复后保留编号未知证据并返回未决。
- Agent 专项最终 15 项、11.611 秒通过，覆盖默认无扫描、全部 assemble 入口、旧任务局部升级、首尾删行拒绝、局部额度恢复、无工具矢量路径及 PDF 版本绑定。
- Agent、本地重建与共同契约组合 34 项、72.667 秒通过；随后新增的两项首尾/裁剪边界已计入上面的 15 项专项。
- 完整回归 227 项、482.891 秒，无失败或跳过，全部通过。
- CI 合成重放通过：3 条谱行、1 页矢量 PDF、无嵌入位图，重复导出字节相同，4 类拒绝检查通过。命令为同一隔离环境下的 `python ci/verify_agent_replay.py --output work/agent-first-cross-host/replay-final`。
- 本机 Python 3.12.12、Linux FFmpeg 4.4.2 下完整回归通过。另执行有限时合成编码、ffprobe 与实际解码探测，返回 pts=0、time_base=[1,1000]；依赖就绪和功能探测均通过。这提供旧版参数路线的真实合成执行证据，新版 fps_mode 路线由能力矩阵模拟验证。
- references 同步检查、compileall 和 diff 空白检查通过。Ruff E701/E702/F821 检查通过。

证据目录为本工作区 `work/agent-first-cross-host/`。`baseline-reproduction.txt` 保存原缺号异常；`agent-final.log` 保存专项结果；`review-targeted-second.log` 保存 34 项组合结果；`full-final.log` 保存最终完整回归。`replay-final/summary.json` 和 `decode-probe-final.json` 保存合成重放与功能探测结果，后者仅保留版本和匿名探测字段。

## 失败与修复记录

首次完整回归 222 项、367.356 秒，2 项自动裁剪修订失败。原因是新契约标记同时存在于显式自动任务，局部裁剪误入人工路线。修复后通过 source_review.producer 区分，保留自动路线的 crop_revisions 与重新冻结语义，两项针对性复跑通过。

统一旧任务升级门禁后，59 项组合复跑中 4 项旧夹具缺少新增证据。测试现显式提交合成 present/evidence，未放宽生产门禁；34 项组合复跑全部通过。

独立标准与规格审阅发现旧入口升级绕过、全曲补证过度、摘要漏计顶层 issues、Windows 清单夹具以及首尾角色继承问题。修复后两轴复核无剩余发现。首尾角色修复要求沿用相同角色的原引用，删除首行或末行不会继承新边界的旧批准。

## 待用户执行

Windows 原生 CI、其他宿主 FFmpeg 实机兼容和 Codex WSL / Claude Windows / 豆包真实整曲路径均待验。当前 Linux 合成测试不替代这些结果，也不解除既有真实来源未决。用户按验收清单记录实际提交、工具版本、PTS/hash、来源处理、调用和每页当前 output_revision 的实际查看。
