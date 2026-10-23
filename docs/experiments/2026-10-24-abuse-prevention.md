# 匿名网站防滥用本地验证

日期：2026-10-24。实施前提交为 `4a0135797b858f5a5a06d1dc8d2ce6e33faa8773`，工作分支为 `codex/parallel-conversions`。

用户确认规则后，明确调用 implement 技能，授权本地实现、测试、审阅和当前分支提交。本轮未访问生产、修改服务器配置或执行远端写入，未读取真实认证。独立 Skill 和用户原有的未知 `docs/research/` 保持原样。

## 实现

同一 IP 最近十分钟限十次、最近二十四小时限一百次成功入队。新任务和显式重试共同计数，取消与入队后的转换失败不退次数，拒收入队不计数。配额事件与入队写入共用 SQLite 短事务，跨连接竞争和重启仍受同一额度约束。超额响应含等待秒数。

运营者使用本机维护命令暂停或恢复新提交与重试。暂停不影响队列领取、已有任务、取消和合法结果访问。任务身份在原到期后再保留三十天，再经 worker 清理返回 404；未到期结果、未知文件和替换物保持原保护。

schema v3 增加提交事件、暂停状态及索引。旧 v1/v2 快照分别显式升级到新目录，保留源快照和原完成/到期时刻。同版本备份恢复保留配额和暂停状态；旧版本没有完整事件账本，升级后的新账本为空，不猜测历史重试次数。

## 验证方法

使用原独立环境 Python 3.12.12，未新增依赖。测试使用公开接口 `Jobs`、HTTP 和本机维护命令，以及合成 IP、能力凭据、文件和可控时钟。合成测试不代表音乐校对或生产压测。

红绿过程确认了以下失败与修复：

- 连续十次提交并取消后，第十一次原本仍返回 201；加入持久滚动计数后返回 429，并在边界恢复。
- 新增暂停命令前，CLI 返回不支持的参数错误；实现后跨 HTTP 重启保持暂停，恢复后可入队。
- 原到期加三十天后仍返回 410；加入身份清理后所有任务接口返回 404。
- 审阅发现大数据库无法暂停。合成 SQLite 写入并释放超过 64 MiB 的页面后，原控制命令返回 `maintenance_limit`。修复后暂停、恢复和提交均通过，备份自身的大小限制保持不变。
- 审阅发现提交事件缺少字段核验。原核验接受文本时间、正负无穷或非法 IP 摘要；修复后备份、核验和恢复均拒绝，源快照字节不变，目标不发布。

核心命令如下，完整程序回归仅在修复和复核后运行一轮：

```sh
PATH="$PWD/work/engineering/2026-10-23-parallel/venv312/bin:$PATH" \
  python -m unittest discover -s tests -v
PATH="$PWD/work/engineering/2026-10-23-parallel/venv312/bin:$PATH" \
  python ci/verify_script_product.py \
  --output work/engineering/2026-10-24-abuse/ci-evidence
ruff check --select E701,E702 src/drum_score
work/engineering/2026-10-23-parallel/venv312/bin/python \
  -m compileall -q src/drum_score tests
git diff --check
```

仓库未配置静态类型检查器，本轮语法编译不作为静态类型检查结果。Ruff 版本为 0.14.14。独立 Skill 未修改，未运行其单独回归。

## 结果与包核验

最终全量程序回归 212 项全部通过，耗时 155.505 秒，无跳过。回归日志位于本地 `work/engineering/2026-10-24-abuse/regression.log`。Ruff、语法编译及 diff 空白检查均通过。

离线 CI 重放通过，合成来源得到三行谱面、一页 A4 PDF，重放 PDF 字节相同，输出覆盖与输入预算拒绝用例通过。证据为同目录 `ci-evidence/summary.json` 和 `fixture-score.pdf`。

首次使用 `python -m pip wheel` 因该测试环境没有 pip 而失败，见 `build.log`。随后通过已安装的 setuptools 82.0.1 后端构建，无网络安装：

```sh
work/engineering/2026-10-23-parallel/venv312/bin/python -c \
  'from setuptools.build_meta import build_wheel; print(build_wheel("work/engineering/2026-10-24-abuse/dist"))'
```

wheel SHA-256 为 `18534ac519e22e039425e3c7281e85af1920f9387b85b9bdcd19d49157cbd3d2`，包内二十九个文件与准确源码逐字节一致，见 `build-backend.log` 和 `wheel-check.json`。本轮未重新安装 wheel 到两套分发验收环境，不将包字节核对当作独立安装或生产验收。

## 规范审阅

独立审阅首次发现一项 P2，新增事件缺少语义核验。补充有限数值和摘要格式校验及拒绝回归后，复核关闭原问题，无遗留发现。规范审阅者独立运行两项修复回归，全部通过。

## 需求审阅

独立审阅首次发现一项 P2，应急暂停误用快照大小限制。修复控制连接并增加大数据库回归后，复核关闭原问题，无遗留发现。需求审阅者独立运行两项修复回归，全部通过。

## 限制与回滚

没有全站每日额度，多 IP 仍能持续占用转换名额。入口请求/下载限速、解码依赖漏洞、系统网络隔离及告警属于后续专项，不声明已解决。正常清理不保证 SQLite 文件立即缩小，也不删除未知残留。

本轮没有线上切换。部署前仍须获得明确授权，使用匹配旧版制作停服快照，再显式升级到新根。保留旧发行、原数据根和核验快照作为回退；切换后产生的新任务不得通过回滚静默丢弃。命令和状态契约见[防滥用方案](../script-product/abuse-prevention.md)及[维护指南](../script-product/maintenance.md)。
