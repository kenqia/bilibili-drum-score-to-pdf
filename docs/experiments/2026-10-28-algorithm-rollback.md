# 2026-10-28 转换算法回退

用户在 main 部署后报告网站整理变慢，并明确授权执行回退、推送和部署。2026-10-28 已将转换算法恢复到上一发行 `2e1ce361abaa79a156fbf6b271fee5096ea1fb12`，正式服务运行 `ee8ce0b5962d8f21e98fed16eb2b0ed761498e1d`。

## 回退范围

`core.py`、`imaging.py`、`fixed_overlays.py`、`registration_flow.py` 和 `video_seek.py` 与上一发行逐字节相同。撤下新增的 score scope、页面转场和 observed restoration 算法。13 份撤下的源码和测试保存在 `experiments/issue88-withdrawn/`，原有适用测试保留，新增 guardian 测试也保留。

一周结构化整理记录、简介心形拒绝策略、schema 5、媒体缓存、临时排版，以及 guardian 清理和 SQLite 容错保持。未修改正式 CPU、内存、空间准入或资源期限。

现场任务排队时间约 0.02–0.23 秒，没有 OOM 或服务重启证据。新算法是本次回退对象，但没有完成同一输入的新旧算法耗时对照，不能据此宣称性能改善倍数。

## 获取失败与最小修复

前两次默认来源私有验收分别在约 1.8 秒和 1.3 秒返回 `unsafe_media_target`，尚未进入转换。另一次尝试因空闲空间不足被 `storage_full` 拒绝。各次失败均由部署事务恢复原发行、配置和数据根，没有开放候选服务。

诊断发现，匿名接口的首选媒体 URL 使用白名单之外的域名，同流备用 URL 则属于允许的 `bilivideo.com`。原下载器能够拒绝首选地址并成功获取安全备用地址；缓存预检查却在容错块外检查首选地址，导致任务提前终止。

`ee8ce0b` 仅把该检查移入已有缓存版本预检查容错块。失败时跳过缓存复用，普通下载继续逐个核验候选地址。媒体域名、公共 DNS、TLS、大小、时长和尺寸规则均未放宽。新增 HTTP 和真实 worker 回归在修复前以 `unsafe_media_target` 失败，修复后通过；独立 marker 证明不安全地址没有触达传输层，安全备用成功且不写缓存。

## 数据保护与切换

原生产数据根为 `/var/lib/drum-score-restore/main-20261028-r2`，当前根为 `/var/lib/drum-score-restore/rollback-20261028-r2`。原备份位于 `/var/backups/drum-score/backup-before-rollback-20261028-r2`。

停接并停止 worker 后，原库与备份完整比较相等。恢复根保留全部 525 个原任务、104 个提交事件、27 个缓存条目和253 条原整理记录；原任务内容、完成时间和期限未刷新。此前私有验收新增的两个终态任务、四条终态记录和相应私有提交事件也保留。四条记录包括一次空间拒绝、提交取消、重试取消和获取失败。

为满足空间准入，将本轮产生且未上线的四个候选发行归档，逐文件 hash、目录和符号链接核验后释放展开副本。归档保存在 `/srv/drum-score/deployment-rollback-20261028/*-inactive.tar.gz`，对应提交为 `3d86727`、`8658c46`、`554b15f` 和 `4f87af7`。未清除业务数据、实验材料或回退备份。

最终部署证据位于 `/srv/drum-score/deployment-rollback-20261028-r3/`。事务事件为 `preflight_complete`、`private_acceptance_passed`、`complete`，且 `public=true`。

## 验证结果

- 回退提交 `f391b98` 的完整程序回归 293 项通过，耗时 545.352 秒；合成重放通过。程序和 Skill CI 均通过。
- 最终发行 `ee8ce0b` 的程序 CI `40670367480` 五项全绿，覆盖 Linux 两个完整回归分片、Windows、合成重放和准确发行；Skill CI `40670367589` 通过。
- 最小获取修复后的缓存模块 23 项通过，耗时 127.038 秒；补强后的安全 marker 回归单独通过。
- 准确提交的 wheel、sdist 和服务器安装包共 42 个文件逐项核验，离线依赖检查与 BBDown hash 核验通过。
- 默认完整来源 `https://www.bilibili.com/video/BV1rH4y1R7Rk?p=1` 使用默认设置成功，没有更换来源或显式选段。提交至终态耗时 56.441 秒，完整私有验收耗时 62.217 秒。
- 完整 manifest、PDF 和两页预览全部下载并核对 hash；`complete` 仍为 `reliable=false`。临时 A5 排版不改变原 PDF hash 和结果期限。
- 实际查看两页预览，未见分页硬切谱行；未逐音符核对，不能视为音乐校对。
- 公网首页、提交、授权查询、取消通过，未授权查询返回 404。连续五次 HTTPS 返回 200。
- web、worker、nginx 和 zju-search 均 active；web/worker 重启数及 OOM 为零；schema 5、提交开放，`record_failed=0`。正式 profile 内容仅替换数据根。

本地证据位于 `work/engineering/2026-10-28-algorithm-rollback/`，包括回归日志、双制品、聚合部署报告和实际预览。签名媒体地址、认证信息及用户记录正文未导出为诊断证据。
