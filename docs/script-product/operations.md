# 运维入口与发行核验

修改网站、准备发行或切换服务器前，从本页核对部署基线、兼容结构和执行顺序。首次安装与域名配置见[部署指南](deployment.md)，数据工具参数见[维护指南](maintenance.md)。历史实验记录只说明当时状态，不能代替当前服务器检查。

## 开发前读取部署基线

在目标机使用本次候选源码的 `tools/service_baseline.py`，显式指定发行、数据库和本服务配置文件。只对受管服务配置求 hash，不传入认证文件。工具不读取任务正文，不输出配置内容，不启动或停止服务。

```sh
python tools/service_baseline.py \
  --release /srv/drum-score/current \
  --database /ABSOLUTE/CURRENT_DATA_ROOT/tasks.sqlite3 \
  --config /etc/systemd/system/drum-score-web.service.d/90-parallel-budget.conf \
  --config /etc/systemd/system/drum-score-worker.service.d/90-parallel-budget.conf \
  > /PRIVATE/baseline.json
```

占位路径须替换为现场路径；先建私有证据目录。配置集合应包括两个 unit 及所有影响它们的 drop-in，不包含其他服务或认证。`release-identity.json` 必须随发行保存，记录准确源码 commit。旧发行缺少此文件时，先从已核验部署证据重建身份，不能猜测 commit。

在服务器用相同参数加 `--expected /PRIVATE/baseline.json` 检查部署漂移。将脱敏清单带回开发机，在候选 checkout 运行 `python tools/service_baseline.py --baseline /PRIVATE/baseline.json --repository /ABSOLUTE/REPO --candidate COMMIT`，检查祖先关系和候选是否识别线上结构。漂移、同号异构或候选未包含线上 commit 时退出 2。任务增加不会改变普通基线。结构指纹使用 `schema.py` 同一规范化规则；即使 `user_version` 相同，异构表或索引也拒绝。

## 兼容关系

下表是当前升级路径的运维入口。可执行结构定义由 `src/drum_score/schema.py` 维护；包版本 `0.1.1` 不能单独标识数据库兼容性。

| 来源结构 | 新发行入口 | 保留内容 |
| --- | --- | --- |
| 已知 v1 | `upgrade-v1` | 已完成结果、完成时间和期限 |
| 已知 v2 | `upgrade-v2` | v1 内容及并行任务状态约束 |
| 已知 v3 | `upgrade-v3` | 另保留提交计数、暂停状态 |
| Issue #82 选项/缓存 v4 | `upgrade-v4` | 另保留实际选项、视频缓存及原期限 |
| 当前 v5 | `verify`、`restore` | 另保留私有整理记录及原期限 |
| 未知版本或同号异构 | 拒绝 | 不写源根，查明匹配旧发行 |

v1 至 v4 升级新建缺少的结构，不伪造历史整理记录。恢复只写不存在的新根，核验全部文件后登记新 inode/ctime，原完成和到期时刻不刷新。旧程序始终配套旧根。

## 构建准确发行

在 Python 3.12 独立环境安装 `build==1.6.1`。这是开发/CI 构建工具，不增加应用生产依赖。唯一发行入口如下：

```sh
python tools/build_release.py --commit COMMIT --output /ABSOLUTE/NEW_RELEASE_OUTPUT
```

输出目录必须不存在。工具从指定 commit 执行 `git archive`，在临时干净目录构建 sdist 和 wheel，隔离工作区 `build/`、未提交文件和 `PYTHONPATH`。构建后核对两个包的完整 `drum_score/` 文件集合和字节；任一额外、缺失或修改文件均失败。`release-identity.json` 保存准确 commit、逐文件 SHA-256 和两个包的 SHA-256。构建失败的目录不可部署；保留排查，换新目录重建。此清单是完整性证据，不是签名。

CI 的 `release` job 调用同一命令，应用回归继续使用已有两个分片。安装版依赖检查、CLI/HTTP/worker 验收仍按[验证指南](../verification.md#验证安装产物)执行。部署工具再对独立 venv 内全部包文件核验，拒绝旧模块残留。工具当前只接受 Ubuntu/Python 3.12 发行目录布局。

## 准备与执行升级

服务器变更须在明确授权范围内执行。切换脚本只负责已经准备好的发行、配置和配套数据根；备份、升级和真实来源验收沿用现有维护命令。

1. 核对基线与候选祖先关系。用上述入口构建，安装到新发行的独立 `venv`，核验 BBDown、包 hash、`pip check` 及仓库外合成转换。把发行清单放入新发行根。
2. 停止 HTTP 接收，排空所有未完成任务，再停止 worker。使用匹配旧发行进行停服 `backup` 和 `verify`，再用新发行对应入口恢复到不存在的新根。检查完成/到期时间、选项、计数、暂停与缓存不变。两服务保持停止，源根不再写入。
3. 关闭所有数据库连接并完成 WAL checkpoint。分别执行基线命令，加 `--stopped-snapshot`，保存 `old.json` 和 `new.json`。旧清单配置集合包括两个 unit、所有 drop-in，其中即将替换的两个 profile 在计划中单独登记；新清单配置集合是预先准备的四个私有/正式 profile 文件。数据文件 hash 在切换停服屏障后再次比较，拒绝准备后改变的根。
4. 准备 `plan.json`，格式见下例。四个新 profile 都使用 `/srv/drum-score/current/venv/bin/` 和同一个新数据根；web 私有 profile 仅监听独立本地端口，worker 两份内容相同。正式 profile 保持授权的存储、期限和 cgroup 资源参数。`private_check` 是已审阅的参数数组，无 shell 展开，失败返回非零。该命令应验证真实来源的全部产物 hash、整理记录与必要的取消/重试，再恢复原暂停状态。
5. 执行 `python tools/deploy_release.py --plan /PRIVATE/plan.json`。默认只读，成功后才使用 `--execute --report /PRIVATE/deployment.json`。工具持有本服务切换锁，以 exclusive/no-follow 创建新报告并保护后续身份，备份原 profile，停服务、切换配置和 current，核对 systemd 实际 ExecStart 与已验收 profile 完全一致，再启动并检查私有 HTTP，运行 `private_check`，再开放正式端口并检查首页。只操作两个 drum-score unit。
6. 核对公网 TLS、提交/查询/取消及服务资源，保存最终状态。首页检查只是 HTTP 可用性，不代表音乐校对或完整公网验收。更新工程交接，保留旧发行、旧根、快照和 rollback 目录。

用以下 Python 片段组合清单，替换示例路径和验收命令。它只写本地计划：

```python
import json
from pathlib import Path
plan = {
    'old': json.loads(Path('/PRIVATE/old.json').read_text()),
    'new': json.loads(Path('/PRIVATE/new.json').read_text()),
    'current': '/srv/drum-score/current',
    'profiles': [
        {'role': 'web', 'path': '/etc/systemd/system/drum-score-web.service.d/90-parallel-budget.conf',
         'private': '/PRIVATE/web.private', 'public': '/PRIVATE/web.public'},
        {'role': 'worker', 'path': '/etc/systemd/system/drum-score-worker.service.d/90-parallel-budget.conf',
         'private': '/PRIVATE/worker.private', 'public': '/PRIVATE/worker.public'},
    ],
    'private_port': 8792,
    'public_port': 8791,
    'private_check': ['/ABSOLUTE/NEW_RELEASE/venv/bin/python', '/PRIVATE/accepted-smoke.py'],
}
Path('/PRIVATE/plan.json').write_text(json.dumps(plan, indent=2) + '\n')
```

## 失败与恢复

配置发布后立即登记 inode/hash，再 fsync 父目录。私有验收前后但尚未开放正式端口的失败，恢复原 profile、旧发行链接和旧数据根，然后启动旧服务。报告写失败不会阻止恢复。外部替换了配置或 current 时停止自动覆盖，报告 `rollback_incomplete`，按私有 rollback 目录人工核对后恢复。

正式开放边界之后，失败只停止 web 接收并保留新根和新任务，worker 可继续收尾。不要自动把旧库当作新任务的替代品。再次切换必须先暂停并保存新任务，重新制订迁移方案。

工具处理进程内异常；断电或整进程 SIGKILL 后需要人工恢复。先停止两服务，从 `deployment.rollback/plan.json` 确认旧发行、数据根和 profile 路径，核对各配置备份及现场身份，再恢复完整配套组合。报告写入不可用时以现场状态和备份为准。工具不清理旧材料。

## 日志契约矩阵

`tests/test_video_cache.py` 使用 HTTP、真实独立 worker、真实合成媒体和受控外部传输，`tests/record_contracts.py` 核对结构化记录。以下场景均检查输入、实际设置/预算、程序版本、开始/结束时间、168 小时期效及能力凭据未泄露：

| 场景 | 额外断言 |
| --- | --- |
| 首次下载、缓存命中 | 下载数、来源/缓存身份，完整 manifest 与实际发布文件相等 |
| 共享下载失败 | 两任务各有独立失败记录，错误码、失败阶段、resolved URL；仅一次下载 |
| 下载中取消 | 取消者记录终态，其他等待者继续完成，完整 manifest 保留 |
| HTTP 显式重试 | 创建新记录，保留原失败记录及原期限，成功记录保存完整 manifest |

合成故障验证见 `tests/test_release_guardrails.py`。这些测试不访问真实认证、不修改服务器、不构成真实音乐校对。
