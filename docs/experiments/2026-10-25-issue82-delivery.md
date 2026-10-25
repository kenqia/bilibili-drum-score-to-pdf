# Issue #82 本地交付与验收边界

2026-10-25，在 `codex/issue82-integration` 集成高级选项、自动谱区、有界配准补帧、分散画面预检和受管原视频缓存。保留并行员工已提交的在线人数、默认紧凑分页、临时打印排版和 YouTube 撤回。原工作区及未知文件未修改，独立 Skill 未修改。

## 工单状态

| 工单 | 本地状态 |
| --- | --- |
| #83 高级选项 | 已实现，公开Python/CLI/HTTP参数、重试、选段和显式v4升级验证通过。 |
| #84 配准与预检 | 代码和工程回归已完成。窄重叠真实来源恢复；多面板自动选区与固定覆盖物的真实同类改善仍缺验收证据，不能标记全部验收完成。 |
| #85 视频缓存 | 已实现，受管身份、独立协调、取消隔离、容量、损坏拒绝和恢复验证通过；真实来源两次worker为fill→hit，原期限不续期。 |
| #86 集成 | 254项回归、最终八路容量、独立安装、真实重放与浏览器验收已运行，结果和限制如下。 |

未push、创建PR、关闭远端工单、部署或迁移生产库。GitHub只读回读多次EOF，按留存规格和发布记录实施，不重复创建工单。真实验收补齐前，不应关闭父工单或宣称全部规格验收通过。

## 精确源码与安装包

应用验证提交为 `332d6893c30b162d82603622f0b4b3aedf1e072b`。构建提交 `fe782152d9d937acae951cf989e742e88f1abfc1` 只增加验证文档。后续集成 `e7203309c27536c111e470a77c25e1e81de39644` 也仅合入文档。最终源码、wheel和两套独立安装环境的40个包文件逐字节一致，包括网页静态资源。

wheel为 `bilibili_drum_score_to_pdf-0.1.1-py3-none-any.whl`，SHA256：

```text
fcd55f8a810bbc3549bd4af1329ba3f88d7a51c8152f161c64023cecf32abed4
```

sdist SHA256为 `7d9cef89aaa22b4244413da876829fd77456dac4f39a0f04e651683d08032652`。持久副本中的 `build-identity.json` 保存完整包文件hash及安装报告。基础和web两个新环境从仓库外运行Python和实际CLI，依赖检查通过。web环境运行实际HTTP/worker、缓存命中、临时A3排版、原PDF/hash/期限不变，以及停服backup/verify/restore、新文件身份和未知schema拒绝。未把合成传输当作真实联网。

## 新鲜工程验证

Python3.12.12完整程序回归254项全部通过，349.703秒，无跳过。离线CI重放通过，2.478秒；分片127+127，无交集且并集等于完整发现。Ruff E701/E702、Python编译、JavaScript语法和diff检查通过。未配置静态类型检查器，未运行独立Skill回归。前两次251项回归失败与fixture修复见[集成验证](2026-10-25-issue86-integration.md)。

最终源码八路容量8波通过，40 complete、1 cancelled、2受控失败，全部成功均实际触发补帧。热八路媒体读取为零、Range检查8次、原期限不变。峰采样RSS1078263808字节、最多50线程。未设置硬cgroup，硬内存限制为null，本机结果不代表生产容量或速度承诺。持久记录为 `capacity-report.json`。

## 最终安装版真实来源

十三个原失败来源用同一最终wheel从仓库外重放，无重新获取或转码，原hash全部保持。仅一个恢复，另外十二个仍受控失败，未发布部分结果。

| 来源p1 | 最终结果 |
| --- | --- |
| BV1fbFczHE1r-p1 | complete，22行/2页 |
| BV16pnV64EoX-p1 | unsupported_layout |
| BV1Xp4y157oo-p1 | discontinuity |
| BV1FtnP6AEfA-p1 | discontinuity |
| BV1JU4y1y7Zy-p1 | discontinuity |
| BV1hgnb6DELn-p1 | discontinuity |
| BV1M216BVEE1-p1 | discontinuity |
| BV1r9MyzYETL-p1 | discontinuity |
| BV17cxvenEBn-p1 | discontinuity |
| BV1AFyZByEV4-p1 | discontinuity |
| BV1g6XrYGEy1-p1 | discontinuity |
| BV1zV411W7Hj-p1 | discontinuity |
| BV15R4y1n7Ch-p1 | discontinuity |

恢复来源 `BV1fbFczHE1r` 完整245.3秒、22行两页。最终安装版PTS/time_base/采样hash、placements、region、长图和页区域与f0131af恢复结果一致。Root实际查看最终两页，标题、署名、A/B/C、后续重复与123末行终止线可见。

未参与调参的保留来源《鲜花》 `BV1Yw4m1Y7YH` 在最终wheel下仍为27行三页，用时29.484秒。全部PTS/time_base/采样hash、placements、region和长图与冻结旧基线逐项相同。Root实际查看最终三页，标题、作者、署名、后续重复与110末行终止线可见。所有自动结果仍为 `reliable=false`，工程看图不是逐音符音乐校对。

失败内部阶段成本和失败区间未知时保持null。其余十个来源没有逐帧因果诊断，不根据相同错误码推定原因。真实缓存两次worker另有fill→hit、媒体获取1→1、Range1→2、24h期限不续期证据；两次均为选段，不能当整曲改善验收。

## 最终安装版浏览器

真实Chromium在安装版HTTP和持续worker上提交 `[0.5,1.5)`、手动全画面、关闭覆盖物忽略的合成任务。默认一页切换临时A3三页，全部预览解码、实际下载、390px手机无横溢出和刷新恢复默认通过。原PDF hash与期限不变，无pageerror。Root实际查看手机全页，pdfinfo确认为三页A3。测试后服务器、worker及已记录后代身份退出。

此项验证合成媒体的浏览器与生命周期，不能当真实音乐验收。报告及进程清理副本为 `browser-result-report.json` 和 `browser-process-cleanup.json`。

## Standards

独立规范审查覆盖固定基线 `b6b8220deefc5e93d4495089103173efa4acf927...332d689` 和修复增量，0 findings。检查项目约定、独立Skill边界、匿名获取、缓存持有/取消/配额、精确身份清理、显式升级及恢复原期限。完整报告为 `review-standards.md`。

## Spec

初审通过公开入口复现了较大空白面板抢占较小真实谱区。单一修复实施者完成红绿回归，最终自动与手动均完成四行、边缘RGB保留。增量复审确认该实现缺口解决，未发现新增确定实现错误。

真实多面板自动选区与固定覆盖物改善仍缺对应同类证据。另查看十个真实来源的20秒画面；大中央Logo来源 `BV1JU4y1y7Zy` 的 `[10,50)` 开关对照均为discontinuity，未证明真实遮罩改善。首次外置脚本因缺少multiprocessing主入口保护失败，已标为脚本错误，修正后才记录上述两次产品结果。不能把合成测试或单点画面静止当成真实改善。

两轴分别为Standards 0项；Spec 0项未解决的确定实现缺口，1项真实验收限制，涵盖上述两类。完整报告为 `review-spec.md`。

## 持久产物与证据缺口

稳定副本位于工作区 `work/engineering/2026-10-25-issue82/deliverables-final/`，含恢复来源PDF及全部两页、保留来源前后PDF及各三页、wheel/sdist、逐文件hash、真实来源/看图/浏览器/容量/审查报告。收尾时32个副本文件的hash全部与 `delivery-index.json` 一致。

收尾核验发现原 `/tmp/drum-issue82-context/` 已不可用，原因未确认。其原视频、原生采样、长图、原始日志、外置脚本及临时安装环境当前无法回读，不声称这些中间证据仍然保留。已运行结果有本轮工具回执、提交文档和上述持久报告；复现完整实验须重新准备来源及独立环境。交付目录里的原manifest引用原生中间产物，但这些文件未随副本复制。

六个已合并且干净的实施工作区已通过普通git worktree remove清理，分支保留。原工作区、集成工作区及其他员工的prototype工作区保持原样。
