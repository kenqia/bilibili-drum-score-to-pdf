# Agent-first 跨宿主验收清单

本清单由用户在目标宿主执行。记录实际源码提交、安装提交、Python/FFmpeg 版本和结果；未执行项标为待验。仓库自动测试不证明 Agent 实际看图、真实生图或整曲完整。

## 准备独立环境

1. 使用本轮提交的独立源码或安装副本，保留原安装和任务。安装器只安装已提交快照，未提交源码不会进入安装包。安装、备份和回滚说明见 [安装指南](../install.md)。
2. 使用 Python 3.12、固定 requirements、ffmpeg/ffprobe 和 Poppler。Windows 使用原生命令行，建议 `python -X utf8`；WSL 测试不能记为 Windows 原生通过。
3. 在 Skill 根目录运行以下命令。它只读取公开 Skill 入口与依赖，不读取认证，不联网。

```sh
uv run --python 3.12 --isolated --with-requirements scripts/requirements.txt python scripts/host_check.py --probe-decode
```

确认 prerequisites_ready 与兼容 runtime_ready 的含义是依赖就绪；decode_probe.status=passed 才表示本次合成解码通过。宿主看图、生图能力另行核对。其他 Skill 不可读时应有 warning，但有效目标仍能发现。

## 默认 Agent 整曲路径

向宿主 Agent 提供真实视频或公开 B站链接及新的任务目录，并要求按当前 Skill 执行以下过程。请求字段见[阶段协议](stage-recovery-layout.md)。

1. prepare 后读取默认 stage。预期 phase=source，尚无冻结，不主动增加 sparse/strict 扫描、自动截图或看图记录。读取已有 captures、首尾采样建议和字段模板。
2. navigate/capture，实际查看每张用于选行的原生图，再 present。按原谱顺序确定 position，保留标题、速度、拍号、首尾与行外记号。同位置选更好来源，不同位置重复音乐保留。
3. assemble 提交标题、音乐起点、末行、相邻谱行的 evidence。已有自动疑点通过 source-issues 逐项登记处理；真正无法确认的音乐保持 unresolved。确认只是光标的变化可以在保留自动原记录后解除。
4. stage 应进入裁剪检查和生成阶段，不要求先解决自动导航内部状态。裁剪穿过记号、损坏 hash 或隐藏音乐未解决时仍应阻止继续。
5. 无真实生图工具的宿主执行 redraw-inputs，再逐组 fail-redraw(outcome=unavailable)，填写真实理由。不要为验收伪造 begin/dispatch/finish 调用；有合法 calling 时先恢复，不能重发。若使用真实生图，保留实际调用回执和逐张审阅依据。
6. export/stage 取得当前 output_revision 与全部有序预览。实际查看每一页，再 review-pdf 提交全部页码、具体 notes 和该独立版本。最后 stage=complete 才视为交付。

建议采用 KiLLKiSS、BV1rH4y1R7Rk 与另一作者“小星星”的三首历史来源范围，分别建立本轮独立任务；历史批准不能代替本次实际判断。检查 KiLLKiSS 第31小节遮挡是否由真实局部补采解决。若只验收片段，明确 scope，不能记为整曲成功。

## 恢复与拒绝场景

| 场景 | 预期结果 |
| --- | --- |
| 显式 sparse 与 strict | 都可执行，稀疏接续与连续时间覆盖分别记录，预算停止不冒称完整 |
| 同位置重叠 | review-overlap 保留备用来源，revise-selection 明确选源；原位置只打印一次 |
| 不同位置重复音乐 | 所有原谱位置保留，即使像素或音乐相同 |
| 缺号与残行 | 不抛混合数值比较异常，不猜编号；返回未决与恢复动作 |
| 局部修订 | 只补交受影响位置和接续依据；无关生成组、调用与修正额度保留 |
| A→B→A | 恢复 A 的原额度和已有结果；calling 不重发 |
| 新候选 | include-candidate 不增加严格时间覆盖，新增来源需审阅 |
| 长回执 | --summary 与 --output-format summary 字段一致，details.path 的完整回执可读 |
| 旧 PDF 版本、缺页或损坏 | review-pdf 拒绝批准，旧文件保留 |
| 旧合法人工冻结未改来源 | 恢复不强制补新证据，不重新扫描 |

## Windows 安装与自动验证

在 Windows 原生 Python 3.12 运行以下命令，测试使用独立临时安装目录，不修改共享 Skill：

```sh
python -X utf8 -m unittest discover -s tests -p test_skill_install.py -v
python -X utf8 -m unittest discover -s tests -p test_host_check.py -v
python -X utf8 -m unittest discover -s tests -p test_cross_host.py -v
python -X utf8 -m unittest discover -s tests -p test_agent_source.py -v
python -X utf8 -m unittest discover -s tests -p test_public_contracts.py -v
python -X utf8 -m unittest discover -s tests -p test_stage_cli.py -v
python -X utf8 tools/sync_skill_references.py --check
```

确认中文文件以 UTF-8 保存，installation.json 的 files_sha256 使用 `/`，升级与回滚保留非管理任务，非法旧清单仍拒绝。CI 使用相同重点套件；远端结果取得前只记为已配置。FFmpeg 4.4.2 真实环境与新版本分别检查 capture 和显式 strict 的实际 PTS，不能只测试参数字符串。

## 保留证据

每个场景记录以下内容，不复制令牌、Cookie、认证、原始敏感日志或签名媒体 URL：

- 宿主、源码及安装提交、工具版本、输入 BV 或本地公开标签。
- 任务与原始来源位置、实际 PTS/time_base/hash、导航和原生截图数、实际呈交数。
- 来源审阅、旧疑点及处理依据、局部修订、生图实际调用与修正次数。
- PDF output_revision、页数、全部页面实际审阅结果、未决项和保存决定恢复。
- 耗时与已知成本，未知成本保持 null。

按 Codex WSL、Claude Windows、豆包分别填写通过、失败或待验。把失败停留的操作、稳定 error.code、脱敏证据和最小复现步骤交回，保留原任务与旧输出。
