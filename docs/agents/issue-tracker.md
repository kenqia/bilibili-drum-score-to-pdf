# Issue tracker

项目跟踪在 https://github.com/kenqia/bilibili-drum-score-to-pdf 。Agent-first 规格是 #32，任务图是 #33 至 #41。标签 ready-for-agent 表示可由 Agent 接手，是否可开始由原生 blocking 关系决定。

实施工作汇入 integration/agent-first，通过 PR 的 closing references 收尾规格与任务。草稿 PR 验证完成后转为待审阅，不自动合并 main。Issue 和远端写操作遵守用户授权，父规格不因拆票而关闭。

端到端性能规格为 #43，任务图为 #44 至 #52，依赖和验收状态见 [实施状态](performance-implementation-status.md)。用户确认 #46 至 #50 先在 `codex/issue-43-software-experiment` 完成隔离软件与合成验证；完整真实基线和快路径放行仍待验收。本地实现不等于远端工单关闭，当前没有远端写入。

2026-10-10，用户确认按[最小兼容提案](fast-path-compatibility-proposal.md)继续 #51 的隔离实验软件实现。授权覆盖显式新任务的脚本/Agent 分别接受依据、有限旁记录和共同复验，保持默认关闭、旧任务与旧决定重放。#45 的完整真实基线、#51 的真实支持范围和 #52 的质量及耗时/Token 配对放行仍须验收；此次确认不包含默认启用或远端写入。
