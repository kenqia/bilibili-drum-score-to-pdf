# #74 本地部署与维护演练

本轮提供停服备份、核验、新目录恢复和整服务树终止后的暂存恢复，同时准备 systemd、nginx 与迁移回滚指南。仅在 WSL/本地演练，未向服务器写入、修改 DNS、签发证书或开放公网。目标主机硬 cgroup、真实沙箱及既有站点回归仍待明确授权后验收，#74 不能据此称为上线完成。

## 环境和产物

实施树 `/home/kenqia/issue74-deployment`，基线 `7780715f88aa12637762c60bf1c2b8c8193ec79a`，Python 3.12.12。新维护命令随基础包安装，不新增生产依赖。域名候选由用户确定为 `drum.kenqia.top`。部署配置与可回滚步骤见[部署指南](../script-product/deployment.md)，维护边界见[维护指南](../script-product/maintenance.md)。

外部证据根为 `/home/kenqia/issue69-context`。准确源码无缓存构建 sdist 和 wheel，23 个包文件与源码、sdist、wheel逐字节相同。最终 wheel SHA-256 为 `ec090bd0f0e480273699a43f609eafa77246d53ae035872f1759a8b705c1cbf2`，sdist 为 `3cb7a9a7844bc81d5a97d84d0c13cd54b4f20516261dd992602ec789b9d16b88`，细项见 `deployment74-packaging/identity.json`。基础环境 `/home/kenqia/issue74-base-final-venv` 从本地 wheelhouse 离线安装，依赖检查通过，无 FastAPI/Uvicorn。

## 定向行为与失败证据

维护 CLI 的首次缺模块测试、额外文件拒绝缺口、清单条目计数缺口以及发布后父目录 fsync 失败的错误信息缺口，分别保留实际 RED 与修复后的 GREEN。多页结果最初夹具只生成单页，该失败是夹具前提不成立，不能当作功能 RED。HTTP 写屏障最初夹具在屏障后初始化 app，导致初始化被锁；修正为屏障前创建应用后，真实提交返回 503、释放后可正常入队。

维护测试核对一致数据库、真实合成多页 PDF 和所有页 hash、恢复后的正式 worker、原任务身份与期限，以及新 inode/ctime 到期清理。恢复不启动业务、不复制未完成视频、锁或机器配置。坏清单、路径逃逸、额外文件/空目录、链接、FIFO、未知 schema、损坏库、worker 锁忙、SQLite 写忙和资源限额均拒绝。

独立预检曾复现 schema 比较把索引字符串常量降为小写，以及 queued 的本地路径来源被接受。修复后保留 SQL 字符串大小写，恢复输入复用公开 URL 规范化边界，并检查任务身份、摘要和有限时间。随后发现 `LIKE 'sqlite_%'` 把下划线当通配符、忽略用户表 `sqliteXextra`，新增真实 CLI 拒绝 RED 后改用精确前缀的 GLOB 过滤。`maintenance74-sqlite-prefix-{red,green}.log` 和 `premerge74-review.md` 保留过程。

复制、写清单和排他发布前三个阶段的真实维护进程均执行 SIGKILL。未发布目标，私有残留不能 verify/restore，重跑不接管残留。并发修改来源在复制后返回 `source_changed`。外部 I/O 边界注入 ENOSPC、嵌套目录 fsync 和发布后父 fsync 失败，检查只清本次暂存、不覆盖旧备份、已发布完整目录保留及诚实 `output_published=true`。这些是合成故障注入，不是实际磁盘满或断电验收。

整服务树强杀的原缺口由独立探索确认，包含 guardian 的六个进程终止后仍有 159892 字节获取视频和 PNG 残留。仅杀 worker 的对照由 guardian 清理成功。新协议在 spawn 前持久登记空私有根，整树 SIGKILL 测试由 RED 1.390 秒变为 GREEN 1.555 秒；替换根、替换 marker、外部 symlink、未知根和 attempt 用户文件保留。所有权覆盖已登记私有根内转换暂存，不声称逐临时文件持久 ledger。不是实际 OOM 或 cgroup 试验。

## 新鲜验证

运行：

```sh
PATH=/home/kenqia/issue72-web-venv/bin:$PATH PYTHONPATH=tests:src \
  /home/kenqia/issue72-web-venv/bin/python -m unittest discover -s tests -v
```

`full74-final.log` 为 148 项、110.479 秒、全部通过，无 skip。分片列表为 74/74，并集与完整发现相同且无交集。`ci74-final/summary.json` 的合成双跑 PDF 相同、全部预览、A4 与拒绝检查通过。Ruff E701/E702/F821、compileall、diff check、Git connectivity 与改动文档相对链接通过。部署四模板 hash 与 Root 已验版本相同。

Root 的独立 nginx 1.18 前缀、高端口及合成证书演练覆盖 HTTP 前置 503、ACME、HTTPS 跳转、认证透传、XFF 覆盖、8 KiB 413 和持续分块累计 408；原 default/API 使用 stub，不代表真实既有站点。systemd 249 verify 只替换安装路径，退出 0，未启动 unit。证据为 `deployment74-config-report.md`、`evidence/deployment74-nginx/report.json` 和 `evidence/deployment74-units/report.json`。模板采用 OOMPolicy=stop/KillMode=mixed，不把它们当作已验证的整树恢复。

## 最终安装与真实浏览器

新基础环境和 web 环境均离线安装并通过依赖检查，基础环境无 FastAPI/Uvicorn。`deployment74-packaging/{base,web}-smoke-report.json` 核对全部 23 文件与准确 wheel/源码一致，从仓库外以安装版 CLI 转换并读取实际 PTS、来源 hash、PDF 和全部预览。web 环境实际启动 HTTP 和独立 worker，显式 2 秒期限后状态/PDF/预览统一 410，受管文件物理清除。

`maintenance-smoke-report.json` 从仓库外调用安装版 backup/verify/restore，恢复后启动正式 worker 和 HTTP，核对 durable finishing 恢复完成、遗留 running 变中断、原完成/到期时刻与全部页面 hash。显式 4 秒期限实际等待后，三个入口返回 410，新身份受管文件物理清理，备份仍完整。首次夹具试图同时放置 finishing 和 running，违反合法 `single_active` 约束而未领取任务；改成两个独立合法快照后通过，没有修改生产代码。失败日志保留为 `maintenance-smoke-fixture-failed.log`。

Root 在最终 wheel 的全新 `/home/kenqia/issue74-offline-final-venv` 上完成真实匿名小星星浏览器验收。独立 Chromium context 实际取消、重试、SIGTERM 中断、再重试、关闭后返回、全部预览及按钮下载；PDF SHA-256 `8064538f70851edc4f66702ea2bdf979d1188411c1c222f2d125a56523b873c2` 与认可版相同。显式 20 秒期限后，状态/PDF/预览全 410 且物理清除。5 张桌面与 390 宽截图已实际查看，无布局溢出或脚本异常。没有逐符号音乐校对。

真实浏览器证据为 `browser74-installed-final-report.md` 和 `evidence/website74-installed-final/browser-report.json`，session48681退出 0。100ms 服务树 RSS 采样峰 356347904 字节，仅为 WSL 采样，不是 cgroup 硬峰、服务器资源验证或上线证据。临时浏览器服务已停止；原用户预览及数据保持。

## WSL 文件系统故障

离线安装首次写日志时出现 EROFS，随后 shell 临时文件及 git/python 加载出现 EIO，所有写盘与测试暂停。文档 heredoc 尚未启动，没有把失败操作记为成功，也未 remount 或删除数据。用户重启后重新验证写/fsync/读/unlink、Git对象、包 hash及全部源码字节。含 NUL 的原日志保留为 `deployment74-artifacts/offline-install-failed-before-restart.log`，新建独立环境重验，不覆盖故障环境。

故障前及 schema 末次修复前的 wheel、离线报告和真实浏览器结果保留于 `deployment74-artifacts/pre-schema-fix` 及对应历史目录，不能替代最终 wheel 验收。准确提交、最终安装与浏览器身份由外部 `deployment74-packaging/final-binding.json` 绑定，未知调用成本仍为 null。
