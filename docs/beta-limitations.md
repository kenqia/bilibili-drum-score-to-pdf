# 同模板真实可用 / internal beta

2026-10-07，基于 `355c9e71e939d0c122050aa5910091985ee2615d` 的真实验收与用户提供的对抗性审查整理。本轮只修改说明与任务状态，不改变获取、滚动、光标或质量算法。

## 已验证的范围

真实 `BV1rH4y1R7Rk` 第一 P 完成 URL 匿名获取、完整顺序恢复与 A4 PDF。H.264 1920×1080、30 fps、298.6 秒，输出 12 行、2 页，`complete=true`，0 人工确认、0 未解决问题，最低 effective DPI 264.182。

同一原视频双跑的谱行、顺序、9 处 seam、背景历史和光标证据一致；两次 PDF 的 150 DPI 全页渲染逐像素一致。已逐页查看全部页面、接续和跨滚动证据，107 项测试串行通过。这是该版本的本地实测记录，不是 GitHub CI check。详见 [真实验收](verification-real-bilibili.md)、[实现状态](implementation-status.md) 和 [审查记录](review-real-bilibili.md)。

适用于白底、多行、纵向向上推进且类似该样本的动态鼓谱。其他布局、频道批量输入、任意缩放和快速滚动均未通过本轮验收。《七里香》目前只有低清布局研究，不能据此声称整曲高清通过。

## 明确剩余问题

| 项目 | 当前行为与影响 | 跟踪 |
| --- | --- | --- |
| P1 候选格式 fallback | 最多枚举三候选；超 2 GiB、unsafe_media_target、media_resolution_mismatch 等 InputError 会提前终止。可用次优轨可能被误拒绝，安全校验不能降低。 | [#20](https://github.com/kenqia/bilibili-drum-score-to-pdf/issues/20) |
| P1 锐度接受门槛 | assess 计算 Laplacian sharpness 用于择优；validate_print_quality 只拦截低于 150 DPI。高分辨率低细节输入仍需人工核查，不能宣称自动保证高清。GaussianBlur 失败不能代替校准。 | [#12](https://github.com/kenqia/bilibili-drum-score-to-pdf/issues/12) |
| P1 中央长期遮挡 | central_obstruction 只证明 held-window 的互补观察。滚动经过长期中央封面遮挡的完整恢复尚未实现，可能保守等待；不得猜补。 | [#18](https://github.com/kenqia/bilibili-drum-score-to-pdf/issues/18) |
| P2 独立 CI | 当前没有 GitHub CI check；已有 107 项通过记录和真实双跑是本地历史验收。 | [#21](https://github.com/kenqia/bilibili-drum-score-to-pdf/issues/21) |
| 使用耗时 | 五分钟样本 URL 全程约 1177 秒，复用原视频约 1170 秒，内部转换约 1155 至 1157 秒。没有几分钟出谱承诺。 | [#22](https://github.com/kenqia/bilibili-drum-score-to-pdf/issues/22) |

## 维护边界

后续先修候选 fallback、校准 #12，再用正文确实长期中央遮挡的真实视频决定 #18 的支持范围。每项从实际失败出发，以现有 CLI 做针对性回归。不因整理仓库重构滚动或光标核心，不通过降低安全或像素证明要求让输入成功。

用户可以开始处理同模板输入，每份新曲仍应核查全部页面、seam 和首尾。`waiting` 表示尚未证明完整；`complete=false` 是明确接受缺失后的结果。保守拒绝并不证明任意输入都会被质量门槛拦截。

## issue 收尾原则

已完成实现与已验收样本的任务以代码和验证记录关闭。旧总规格及绑定《七里香》高清验收的任务按本轮明确的 beta 范围归档，未完成部分由上述独立 issue 接续，不标成全部完成。#12 与 #18 保持开放。正文和测试中的历史记录保留，不改写为今天的新鲜测试结果。
