# 谱行边界合入本地 main

肯恰大人明确要求将已验收版本合入 main，用于改进旧主算法的分页。合并提交为 `a75b12c375ab3517d97db26f5b3a098e1bd75b1c`，第一父提交为原 main `adbcbb0247eff8656698e7e95345af96a94a4840`，第二父提交为验收分支 `41bea3f7e52c7822ea779d743b257de9095576e0`。使用独立合并提交保留整体撤回点，没有 push 或部署。

## 接入范围

保留旧主算法的视频提取、配准、拼接和去重流程，在默认分页与临时重新排版的共同入口细分连续行组。归属先使用已锚定组件，再对悬空组收集同列上下证据，最后寻找保护完整组件的凸凹路径。证据不足、真实跨行连接、无安全路径或超出预算时保留原组。检测 RGB 与交付 RGB 分离，页间使用统一比例。

完整合入 `82f4d68`、`5aa9a6c` 和验收记录 `41bea3f`，未重新调参。全部 56 个程序包文件与验收分支逐字节相同，hash 保存在本轮 `source-identity.json`。没有新增依赖、schema 变化或修改独立 Skill。

## 接受范围与限制

S12、S14 最大行组分别从 13、35 行降为 7、10 行。S12 第 103 小节上方 `o+` 留在第 99 小节所在上行块，用户明确接受此已知例外。其余 18 源中 17 源的前后 43 页预览逐字节相同，S09 最大行组三行降为两行，实际看图未发现新增明显错行或记号拆散。仍有未拆开的双行、多行组。

历史独立复核指出，同高度带可能把不同语义对象合并；核心条带接触也不能证明音乐语义上的连接。用户在已知例外和后续页面验证后授权采用当前版本，这不构成所有未来错行均可接受的规则。结果保持 `reliable=false`。

实际看图证据沿用[20 源验证记录](2026-10-29-staff-boundaries-remaining18.md)，因为合并没有改变程序字节。S12、S14 使用与原记录 hash 一致的恢复长图；其余 18 源使用原 PDF 内嵌 RGB 有序重建的派生输入。本轮没有重新获取、解码、拼接视频或重跑专家样本，不是新的 48 源端到端验收。耗时按原报告区分边界分析和总布局，均不含视频处理。

## 合并后验证

验证使用项目已有 Python 3.12 环境，并将其 bin 放到 PATH 首位，不安装新依赖。

```sh
python -m unittest discover -s tests -v
python ci/verify_script_product.py --output work/engineering/2026-10-29-staff-main-merge/ci
python -m compileall -q src/drum_score tests ci tools
ruff check --select E701,E702 src/drum_score/core.py src/drum_score/imaging.py src/drum_score/print_layout.py src/drum_score/staff_boundaries.py src/drum_score/staff_ownership.py tests/test_public_contracts.py tests/test_script_conversion.py tests/test_staff_boundaries.py tests/test_staff_ownership.py
git diff --check
```

合并后完整回归运行 321 项、492.878 秒，320 项通过、1 项失败，无跳过。唯一失败为 `test_processing_records.ProcessingRecords.test_local_cli_exports_records_without_creating_missing_data_roots`，在第 165 行期望退出码 2，实际为 1。谱行边界与归属的 18 项测试、Python/CLI/HTTP 共同约束、临时排版和网站 worker 测试通过。

同一用例在上一轮候选全回归中也失败于第 165 行；上一轮未改 main 与候选单独运行时均较早失败于第 159 行，错误为 `records_unavailable`。这是合入前已存在、尚未定位的整理记录 CLI 问题，不能把本轮回归称为全绿。历史证据分别保存在 `bilibili-drum-staff-boundaries/work/engineering/2026-10-29-vertical-rays/` 的 `full-unittest-v2.log`、`main-baseline-failure.log` 与 `candidate-isolated-failure.log`。

编译、变更 Python 文件 E701/E702 和 `git diff --check` 检查通过。未构建或安装新发行，未运行独立 Skill、Windows CI 或生产验收。离线产品重放通过，重放 PDF 字节一致，输出已存在和资源超限均受控拒绝；摘要为 `ci/summary.json`。

证据目录为 `/home/kenqia/my_folder/bilibili-drum-main/work/engineering/2026-10-29-staff-main-merge/`。此前实验、原 48 源结果和原工作区用户修改均保留。

## 撤回与上线

如需撤回本次算法集成，可在干净工作区使用 `git revert -m 1 a75b12c375ab3517d97db26f5b3a098e1bd75b1c` 创建反向提交，随后同步更新本次状态文档。本轮未执行撤回，也不删除原实验分支。

当前只完成本地集成。线上算法是否切换必须按运维入口另行构建、验证、获得部署授权，不能把本地 main 的行为描述为已上线。
