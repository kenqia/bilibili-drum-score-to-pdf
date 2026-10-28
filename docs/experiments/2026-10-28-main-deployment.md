# main 合并与生产部署验收

候选源码为 `1ac3c1d398ba2cbbf2ee1eef6e5818f73c867b98`。用户明确授权合并 main 及部署。原工作区的未提交配准修改和其他 worktree 保持原样。

## 发行及平台验证

本次修复 Windows CI 未安装 web 测试依赖，以及 Linux 专属 HTTP 写入、worker、临时排版测试的平台边界。Python/CLI 和静态首页继续在 Windows 验证。生产包源码没有因 CI 修复改变；之后的现场缓存备份兼容修复见下文。

候选通过 `tools/build_release.py --commit HEAD` 从干净提交构建 wheel/sdist；两种制品的 45 个包文件与提交字节一致。服务器使用独立 venv、既有离线 wheelhouse 和固定运行依赖安装，`pip check`、包文件逐项核验、BBDown hash 核验通过。此前准确安装候选 `554b15f` 的简介策略和整理记录 12 项通过，4.881 秒；最终维护兼容修复另有 24 项专项及完整 CI 验证。该候选仓库外安装版合成重放通过，三行、一页、三张嵌入图，重复 PDF 相同，输出已存在和资源超限均拒绝。这些结果不是音乐校对。

本地临时排版专项通过，4.499 秒。首轮 Linux 分片中 158 项只有一项因测试辅助函数读取正在退出的 `/proc/<pid>/stat` 而抛 `ProcessLookupError`；另一分片通过。补齐该精确异常后，进程停止专项 5 项通过，0.491 秒。生产源码与上一候选的 45 个包文件逐项相同。独立 Spec 审阅确认准备/验收脚本无阻断；Standards 复核确认最终 Windows 测试调整无阻断。

本地证据位于 `work/engineering/2026-10-28-main-deploy/`，服务器私有证据位于 `/srv/drum-score/deployment-main-20261028/`。不提交能力凭据、私有记录正文、数据库或实际配置内容。

## 切换与恢复材料

旧发行为 `/srv/drum-score/releases/2e1ce361abaa79a156fbf6b271fee5096ea1fb12`，旧根为 `/var/lib/drum-score-restore/records-v5-20261026`。最终新根为 `/var/lib/drum-score-restore/main-20261028-r2`，停服备份为 `/var/backups/drum-score/backup-before-main-20261028-r2`。首次私有失败的根与备份不带 `-r2`，继续保留。

配置变更仅替换配套数据根，私有验收时 web 临时监听 `127.0.0.1:8792`，正式监听恢复 `127.0.0.1:8791`。原 cgroup、并行数、容量与期限保持。nginx、TLS、域名及其他服务不变。

回滚流程见[运维入口](../script-product/operations.md)。私有验收失败恢复旧发行、旧根及旧 profile；公开后失败停止 web 并保留新根中的任务。旧发行、旧根、备份和事务 rollback 材料保留。

## 现场发现的缓存备份兼容问题

main 首次快进到 `4f87af7` 后，准备阶段两次停服备份均由旧工具返回 `invalid_cache_snapshot`，脚本恢复旧服务，未切换发行。只读诊断定位到缓存来源字段白名单遗漏 `description_policy`，没有读取或输出简介、地址正文或凭据。

`1ac3c1d` 只补齐该可选字段的严格校验，不修改数据库结构。普通简介和无有效简介均允许；未知规则、错误布尔类型、命中心形、非空码点及额外字段均拒绝。缓存 backup/verify/restore 与 v4 升级直接核对恢复后数据库策略、原期限和新文件身份。维护及缓存回归 24 项通过，76.266 秒。独立审阅通过。准确安装版在生产旧根上只读核验 56 个缓存文件通过。

本次使用修复后的候选维护工具对停服旧 schema5 根备份和验证，再恢复到新根。旧数据根保留，恢复前后任务与记录元数据在内存逐项比较，不导出正文。

## 最终合并与部署结果

2026-10-28 已将候选快进合并至 `origin/main`。准确程序与网站 CI [40633437102](https://github.com/kenqia/bilibili-drum-score-to-pdf/actions/runs/40633437102) 五项全部通过，Linux 分片分别运行 159 项和 158 项，439.475 秒和 350.624 秒；Windows 合约、合成重放及发行身份检查通过。独立 Skill CI [40633437179](https://github.com/kenqia/bilibili-drum-score-to-pdf/actions/runs/40633437179) 四项全部通过。

服务器 `current` 指向 `1ac3c1d398ba2cbbf2ee1eef6e5818f73c867b98`。停服备份、验证和恢复完成，492 个任务、87 个提交事件、28 个缓存、206 条整理记录及控制状态在恢复前后完全相等。比较包括设置、完成与到期时间和记录内容，只输出计数及比较结果。

首次事务的默认真实来源 `BV1rH4y1R7Rk?p=1` 返回 `unsupported_layout`，部署工具在公开前自动恢复旧发行、旧根及旧配置，两服务恢复 active。前次证据和私有任务保留在原新根，没有覆盖。该来源在当前版本中未恢复默认整理，不能把其他选段成功当作它的默认整曲验收。

第二次事务使用独立 `-r2` 根和证据目录，先验证上述默认失败及完整失败记录，再使用仓库已有正例 `BV1hgnb6DELn?p=1` 的 3 至 218.5000625 秒明确选段。私有验收共 161.746 秒，选段生成两页，manifest 保持 `is_excerpt=true` 和 `reliable=false`；PDF 及全部两份预览 hash 相符。临时 A5 排版成功，原 PDF hash 与原期限不变。取消、显式重试、实际设置、一周期记录及无 `record_failed` 检查通过。事务报告依次记录 `preflight_complete`、`private_acceptance_passed`、`complete`，正式端口已开放。

Root 实际查看两页预览，确认 HURT 标题、署名、首行 1、第二页末行 69 与双终止线可见，原光标及淡水印保留，无新增程序说明。只做工程看图，未逐符号音乐校对；明确选段不是默认整曲成功。当前版本仍保留[已记录的默认来源拒绝限制](2026-10-26-issue93-integration.md)。

公网 HTTPS 首页、提交 201、认证查询 200、取消终态通过；无能力凭据时按现有防枚举契约返回 404。最初公网验收脚本误写成 401，断言失败后核对 `Jobs.authorize` 并修正为 404，再次完整 smoke 通过，未修改生产认证逻辑。首次脚本提交的任务自行结束，无凭据落盘。

服务器连续五次 HTTPS 返回 200。web、worker、nginx 和 zju-search 均 active；web/worker 的 NRestarts 为 0，cgroup memory.events 的 oom、oom_kill 为 0。MemoryMax 分别为 256 MiB 和 1 GiB，CPUQuota 保持 50% 和 150%。两份正式 profile 与切换前备份逐字节比较，仅数据根改变，其他资源及期限参数不变。schema5、paused=0、record_failed=0。

最终服务器证据目录为 `/srv/drum-score/deployment-main-20261028-r2/`，包括 `preparation.json`、`acceptance.json`、`deployment.json`、`postcheck.json`、`resource-check.json`、`deployment.rollback/` 及 `real-artifacts/`。本地对应证据根保留 CI、构建、安装、失败记录与全部页。未更改 nginx、DNS、TLS 或其他应用；未关闭工单。
