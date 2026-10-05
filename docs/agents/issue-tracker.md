# Issue tracker: GitHub

需求和规格保存在 kenqia/bilibili-drum-score-to-pdf 的 GitHub Issues 中。使用 gh CLI，从当前 Git remote 确认目标仓库；必要时显式传入 --repo kenqia/bilibili-drum-score-to-pdf。

- 创建 issue：gh issue create --title "..." --body-file <正文文件>。
- 读取 issue：gh issue view <number> --comments；需要标签或结构化字段时使用 --json。
- 列表：gh issue list --state open --json number,title,body,labels。
- 评论：gh issue comment <number> --body-file <正文文件>。
- 应用或移除标签：gh issue edit <number> --add-label "..." / --remove-label "..."。
- 关闭：gh issue close <number> --comment "..."。

技能要求发布到 issue tracker 时创建 GitHub issue；要求获取相关 ticket 时读取对应 issue 及评论。多行正文使用文件，保留实际换行。

## Pull requests as a triage surface

PRs as a request surface: no.

## 远端写操作

创建、评论、修改 issue 和其他远端写操作须有用户明确授权。授权仅覆盖当次任务，不因存在本配置自动扩大。
