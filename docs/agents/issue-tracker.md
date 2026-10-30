# 工单跟踪

本仓库使用 [kenqia/bilibili-drum-score-to-pdf 的 GitHub Issues](https://github.com/kenqia/bilibili-drum-score-to-pdf/issues)。远端读取前先执行 `git remote -v`，核对目标仓库。

读取规格及实施工单：

```sh
gh issue view 82 --repo kenqia/bilibili-drum-score-to-pdf --json number,title,body,state,url
gh issue view 83 --repo kenqia/bilibili-drum-score-to-pdf --json number,title,body,state,url
```

#82 的留存规格在 [转换改进规格](https://github.com/kenqia/bilibili-drum-score-to-pdf/blob/4d75de5/docs/research/2026-10-24-conversion-improvements-spec.md)，#83–#86 的留存正文在 [工单目录](https://github.com/kenqia/bilibili-drum-score-to-pdf/blob/4d75de5/docs/research/issue82-tickets/)。网络不可用时可以据此实施，但须注明尚未完成远端回读，不重复创建工单。

GitHub 可通过合并关联 PR 关闭实施工单。准备 PR 时使用明确的关闭引用，例如 `Closes #83`；只有全部规格验收完成且用户授权时才关联关闭父工单。推送、创建 PR、修改或关闭工单均是远端写入，须按本轮明确授权执行。#82 当前规格将这些操作排除在实施范围外。
