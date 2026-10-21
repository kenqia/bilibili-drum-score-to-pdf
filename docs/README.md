# 文档导航

第一次使用，从[项目介绍](../README.md)和[安装指南](install.md)开始。AI 检索项目能力时，先读 [llms.txt](../llms.txt)；执行任务时，以 [Skill](../skills/bilibili-drum-score-to-pdf/SKILL.md) 和当前阶段协议为准。

## 使用与任务执行

| 文档 | 用途 |
| --- | --- |
| [安装指南](install.md) | 安装、发现与更新自包含 Skill，验证和回滚。 |
| [匿名网站](script-product/website.md) | 本地安装、独立worker、持久队列、任务链接、取消和恢复；尚未公开部署。 |
| [阶段、恢复与打印布局](agents/stage-recovery-layout.md) | 准备后通过 stage 推进，处理局部改动、调用恢复与全部页面审阅。 |
| [命令入口](agents/reconstruction-entry.md) | 查询 CLI 操作和 JSON 请求字段。 |

## 开发与验证

| 文档 | 用途 |
| --- | --- |
| [架构](architecture.md) | 模块职责、来源完整性、匿名获取和资源边界。 |
| [验证记录](verification.md) | 回归入口、真实样本、确定性重放和仍未解决的限制。 |
| [首发状态](launch-readiness.md) | 已验证宿主与当前交付范围。 |
| [领域术语](../GLOSSARY.md) | 统一谱行、来源、生成与审核术语。 |
| [项目工作约定](../AGENTS.md) | 改动、验收和远端操作规则。 |

## 历史证据

`docs/experiments/` 保存实验结论，仓库 `experiments/` 保存部分任务证据与复现脚本。它们记录当时的实现和验收，不替代当前 Skill 协议；本地绝对路径不保证在其他机器存在。

- [标准曲 PDF 来源与验收](experiments/issue-58-standard-pdf.md)
- [KiLLKiSS PDF 与遮挡修复](experiments/issue-58-killkiss-pdf.md)
- [另一作者《小星星》PDF](experiments/issue-58-other-pdf.md)
- [近似 MIDI 的曲长与回读记录](experiments/issue-58-playable-midi/README.md)
- [新版流程集成验证](experiments/issue-59-final/README.md)
- [自动来源检查与真实未决项](experiments/issue-63-automatic-source-checks.md)

旧版本实现与文档通过 Git history 查看。历史通过不批准新的输入，也不解除当前任务的 blocked。
