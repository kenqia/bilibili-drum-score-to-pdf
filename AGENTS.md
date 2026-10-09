# 项目工作约定

架构与支持范围读取 docs/architecture.md，验证入口和真实验收读取 docs/verification.md，领域术语见 GLOSSARY.md。项目文档使用 unslop 润色。

默认入口为 Agent-first prepare。Agent 实际审阅、提交决定并导出；恢复、补采和有序翻页读取 docs/agents/agent-workflow.md。显式 --operation convert 保留旧 moving viewport 路径。viewport_sampler.py、viewport_tracker.py、candidate_selector.py 合计最多 500 行，测试负责依赖防火墙。Agent 身份提出须通过五线几何和空间顺序检查；候选只能选择单个真实完整原裁剪。任何颜色或像素规则只能影响候选可用性，不能成为身份门槛或重构像素。

运行仓库验证：

```sh
uv run --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt python -m unittest discover -s tests -v
```

修改正常流程后，先跑合成测试，再以 BV1rH4y1R7Rk 的统一 URL 入口双跑验收。记录实际 PTS、完整帧分析数量、实际呈交图像、逐行来源、PDF 分页和已保存决定的双跑一致性。两份独立视觉判断与固定决定重放分别验收，未知模型成本保留 null。真实样本失败先检查 seek、几何、检测和干净候选采集，不新增样本颜色或 codec 例外。

GitHub Issues 跟踪位于 kenqia/bilibili-drum-score-to-pdf，读取时核对 Git remote 与实际仓库。远端写入、PR、合并和 Issues 修改需要明确确认，不自动关闭 Issues。历史实现与旧文档通过 Git history 查看。
