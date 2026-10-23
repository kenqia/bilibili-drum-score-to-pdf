# 八路并行容量实验

2026-10-23，本地已验证最多八个不同 IP 的转换同时执行，同 IP 继续最多一个未完成任务。八路满载处理耗时约两倍的目标尚未验收。生产未部署，也未执行生产压测、OpenClaw 停用或删除。

## 范围与方法

代码基线为 `2fc366aa16fd44ad8594a5b4ad309a01e0f77b55`，本次改造位于 `codex/parallel-conversions`。证据根目录为 `work/engineering/2026-10-23-parallel/`，不作为发布包内容。独立 Skill 和用户的 `docs/research/` 保持原样。

使用 Python 3.12.12 独立环境和离线 `scrolling_video` 合成视频，视频约 24 秒、640 × 520。仅替换匿名下载边界为本地 fixture 复制，实际运行调度器、独立转换进程、guardian、解码、配准、分页和产物发布。没有使用真实来源音乐，也没有音乐逐符号校对。

每种 CPU 亲和设置先运行三个单任务，取处理时间中位数为独占基线。随后分别以 2、4、8 路处理八个任务。表中倍率为该波最慢处理时间除以该设置下的基线，处理时间来自 manifest，排队不计入。整批时长另包含进程启动、排队、调度和发布。RSS 为采样值，不能替代 cgroup 硬限额验证。

WSL 报告的 CPU 拓扑中，0 与 1 属于同一核心。相邻四个逻辑 CPU 对应两个核心，相邻八个对应四个核心。补充实验选择八个不同核心上的逻辑 CPU。这些设置都不能直接映射为腾讯云套餐的 vCPU 性能。

## 测量结果

所有列出的最终波次均为八个任务全部完成。每种设置仅有一轮小规模测量，不代表稳定的百分位延迟。

| CPU 亲和设置 | 独占基线 | 并行度 | 处理时间中位数 | 最慢倍率 | 八任务整批时长 | 调度器树采样峰值 RSS |
| --- | --- | --- | --- | --- | --- | --- |
| 0–3，四逻辑 CPU、两核心 | 0.996 秒 | 4 | 1.459 秒 | 1.68× | 3.899 秒 | 611 MiB |
| 0–3，四逻辑 CPU、两核心 | 0.996 秒 | 8 | 3.120 秒 | 3.31× | 4.182 秒 | 1025 MiB |
| 0–7，八逻辑 CPU、四核心 | 1.019 秒 | 4 | 1.389 秒 | 1.44× | 3.757 秒 | 623 MiB |
| 0–7，八逻辑 CPU、四核心 | 1.019 秒 | 8 | 2.258 秒 | 2.38× | 3.607 秒 | 925 MiB |
| 0,2,4,6,8,10,12,14，八核心 | 1.229 秒 | 4 | 1.849 秒 | 1.66× | 4.568 秒 | 611 MiB |
| 0,2,4,6,8,10,12,14，八核心 | 1.229 秒 | 8 | 2.388 秒 | 2.13× | 3.326 秒 | 1008 MiB |

最终 JSON 为 `benchmark-4cpu.json`、`benchmark-8cpu.json` 和 `benchmark-8cpu-spread.json`。对应日志为 `benchmark-4cpu-312.log`、`benchmark-8cpu-312.log` 和 `benchmark-8cpu-spread.log`。复用 `benchmark.py` 时先将 `venv312/bin` 放到 `PATH` 首位；`CAPACITY_CPU_COUNT=4` 或 `8` 选择逻辑 CPU 数，`CAPACITY_SPREAD_CORES=1` 选择不同核心。脚本会覆盖同名结果，重跑前保留旧证据。

八路功能已成立，目标速度尚未成立。四路在这些小样本中均低于两倍，但不能据此把已确认的八路目标改为四路。八核心实验仍为 2.13×，接近目标也不报告为通过。网络获取、复杂长视频、其他网站竞争及目标机硬限额仍可能增加耗时或内存。

## 失败与修复

早期波次因 SQLite 写竞争导致调度器退出，失败日志和 `diagnostics-*.jsonl` 保留。修复后，同一调度器的短事务由本地锁协调；查询状态与取消轮询使用只读事务；调度器仅重试真实 `SQLITE_BUSY` 或 `SQLITE_LOCKED`。未知提交回执错误必须退出并恢复，不能当作可重试领取，以免重复执行已领取任务。真实外部持写锁超过一秒和领取提交回执丢失均有进程测试。

早期运行使用 Python 3.13 环境，不作为最终 Python 3.12 证据。最终三份容量结果均使用 3.12.12，未开启诊断 trace。没有获得可写 cgroup 内存控制器，因此本次没有 8 GB 硬内存容量结论。

## 回归与安装验证

最终源码执行以下命令，198 项全部通过，耗时 138.414 秒：

```sh
PATH="$PWD/work/engineering/2026-10-23-parallel/venv312/bin:$PATH" \
  python -m unittest discover -s tests -v
```

`regression312-final.log` 记录完整结果。覆盖八任务实际重叠、取消隔离、全部预览/PDF、TERM 和 guardian SIGKILL、维护锁、完成决定回执丢失、FIFO、临时空间预留、v1 快照升级、多页 hash、原期限和新文件身份。`--once --concurrency 8` 仍最多处理一个任务。

离线 CI 合成重放、`compileall`、`git diff --check` 和构建通过。最终 wheel SHA256 为 `95b12fc8c9f5c6186fdb4e984147605b357ff613668f5d91eb4a6e42d74fd4ff`，29 个包文件与源码字节一致。未修改项目发行版本，也未发布该包。

基础与 web 两份独立 wheel 安装均从 `/tmp`、清除源码 `PYTHONPATH` 后验收。基础环境没有 FastAPI，实际转换与全部产物校验通过；web 环境实际启动 HTTP 服务和安装后的 worker，提交、状态、全部预览与 PDF 下载通过。日志为 `installed-base-check.log`、`installed-web-check.log`。两环境没有安装 pip，使用 `uv pip check --python <环境>/bin/python` 检查，分别六个与二十个包均无依赖冲突。

## 后续验收

OpenClaw 卸载参数另用 pnpm 10.31.0、Node 24.16.0 和两个合成全局包隔离验证。首次缺少全局 bin 的子进程 PATH，随后发现 `remove` 拒绝直接传入脚本禁用等选项；改用 `--config.*` 后通过。`pnpm-proof/result.json` 记录指定包与入口消失、另一包与入口保留、包脚本标记未触发。初始失败分别保留于 `result-initial.json` 和 `result-flags-rejected.json`。没有安装真实 OpenClaw，也没有改动用户的全局 Node/pnpm 配置或运行远端卸载。

费用与清理范围见[容量方案](../script-product/capacity-plan.md)。获得具体服务器操作授权后，再对代表性短、中、长真实视频建立目标机独占基线，并以 2、4、8 路测量完成率、排队、处理耗时、cgroup 内存峰值、CPU、磁盘和网络。购买套餐不等于通过验收。
