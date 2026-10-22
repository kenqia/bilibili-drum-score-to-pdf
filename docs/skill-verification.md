# Skill 验证

本页只验证 `skills/bilibili-drum-score-to-pdf/` 和 Skill 安装工具。程序与网站另见[验证指南](verification.md)。两套测试包含同名 fixture 和模块，必须在不同 Python 进程中发现，不将两个目录加入同一个发现过程。

## 运行独立回归

需要 Python 3.12、uv、FFmpeg、ffprobe 和 Poppler。在仓库根目录运行：

```sh
uv run --python 3.12 --isolated --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt \
  python -m unittest discover -s tests/skill -v
python tools/sync_skill_references.py --check
```

两个确定性 CI 分片只发现 Skill 测试：

```sh
python ci/run_unittest_shard.py --tests tests/skill --index 0 --count 2 --list
python ci/run_unittest_shard.py --tests tests/skill --index 1 --count 2 --list
```

分片需要在上述 Skill 依赖环境中执行，二者并集等于完整发现且没有交集。`.github/workflows/skill.yml` 安装 Skill 自己的 requirements，不安装 `drum_score`、FastAPI 或 Uvicorn。Windows 另运行该 workflow 中列出的原生工具与宿主重点测试。

## 核对分发包

`tests/skill/test_skill_package.py` 将完整 Skill 单独复制到仓库外，检查 CLI、宿主发现、便携协议和合成 PDF 重放，不依赖网站包或仓库 docs。`tests/skill/test_skill_install.py` 验证提交快照安装、重复安装、损坏拒绝、任务保留、失败恢复、链接边界与回滚。

Skill 的共同入口矩阵位于 `tests/skill/test_public_contracts.py`。变更其工作流、CLI 或手工恢复入口时扩展这个矩阵，不把网站队列协议加进来。

合成重放可另行执行，输出目录必须不存在：

```sh
uv run --python 3.12 --isolated --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt \
  python ci/verify_agent_replay.py --output /absolute/new-skill-evidence
```

合成 review 声明和确定性重放不代表 Agent 实际看图、来源批准、模型生成或音乐校对。真实任务仍须按 [Skill 阶段指南](agents/stage-recovery-layout.md) 查看原生来源及全部页面；历史未决不因恢复分发而消除。
