# 发布范围与放置中的实验

2026-10-30，已按用户决定发布和部署专家 v6 失败兜底、谱行边界与分页改进。正式发行 `61b5f24` 使用 `main@c3e2ded` 的程序代码，保留原有匿名 B站获取、schema v5、20 GiB 逻辑额度、结果与记录期限。实际验收及回滚位置见[部署记录](https://github.com/kenqia/bilibili-drum-score-to-pdf/blob/4d75de5/docs/experiments/2026-10-30-expert-pagination-deployment.md)。

## 发布范围

| 功能 | 决定 | 证据 |
| --- | --- | --- |
| 专家 v6 失败兜底 | 发布部署；仅默认网站任务的指定失败触发 | [接入验证](https://github.com/kenqia/bilibili-drum-score-to-pdf/blob/4d75de5/docs/experiments/2026-10-29-expert-v6-fallback.md)；48 源批次已实际完成，46 份 PDF、140 页，另两例失败 |
| 谱行边界与分页改进 | 发布部署；保留用户接受的 S12 已知例外 | [main 合入记录](https://github.com/kenqia/bilibili-drum-score-to-pdf/blob/4d75de5/docs/experiments/2026-10-29-staff-boundaries-main.md) |

48 源批次由用户查看交付，不宣称逐符号音乐校对。早期接入记录中的“48 源未执行”只描述当时状态。全部程序结果仍为 `reliable=false`。

## 放置中，不使用

| 实验 | 保留位置 | 执行约束 |
| --- | --- | --- |
| YouTube 运营者账号获取 | `codex/youtube-public-account`，`0878661`；工具试验另见 `codex/youtube-tools-from-integration` | 不接入正式站，不合并、不部署、不启动账号服务或临时出口 |
| 新整理算法、翻页、真实像素恢复 | `codex/quality-design-20261028` 等已有实验工作区 | 不用于本次发行，不续跑已停止批次 |
| 性能优化 | `codex/perf-hot-path-20261028` 及 quality 开发线 | 保留实验及未提交内容，不整条合并、不部署 |

除用户删除的两项外，保留现有分支、来源和实验材料。后续只有用户明确恢复这些实验时才继续使用。

## 已删除的改动

- S06 下缘去重：在 quality 实验工作区撤回 `1772100` 的实现、活动说明及专属测试。保留通用来源与滚动断言，迁移说明见该工作区的 `docs/test-migration.md`。本次 main 从未包含该实现。
- 当前旧配准恢复：在 `codex/discontinuity-recovery` 撤销已核对的 11 个跟踪文件修改，并删除未跟踪的 `src/drum_score/alignment.py` 和 `tests/test_alignment.py`。其他未跟踪文档、锁文件及实验原始材料不属于删除集合。

本次不改独立 Skill，不关闭 GitHub 工单，不修改 DNS、TLS、认证及其他应用。
