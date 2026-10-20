# 项目工作约定

架构与支持范围读取 docs/architecture.md，验证入口和实际验收读取 docs/verification.md，领域术语见 GLOSSARY.md。文档使用 google-developer-docs 编写，unslop 润色。

正常 PDF 任务使用 `prepare → stage` 自动长截图，默认原图直排。Agent 整体查看长图及原生首尾，用 review-longshot 提交谱名和备注，再按连续条带等比分页，保留页内原行距。查看最终全部页面及分页切口两侧的渐强、圆圈等；有疑问通过layout(page_breaks)把相关行留在同页，允许留白或多页。轻微模糊、底色、蓝标和水印可保留，不逐符号校对或逐行填来源。同位置重叠去重，不同位置重复音乐保留。

局部去水印仅处理实际确认没有音符、五线、标题和署名的区域，保留原图及修改记录。明显漏行或重复先重拼，严重遮挡优先 capture 后 repair-longshot，从真实原帧等尺寸替换并重新整体查看；仍无法恢复时说明限制，不猜隐藏符号，不把已知缺段称完整谱。

字段读取 docs/agents/reconstruction-entry.md；清理、补采、重拼和打印布局读取 docs/agents/stage-recovery-layout.md。用户明确要求重绘或矢量时，pdf-route 选择可选路线，未知调用先恢复原 ID，每块每输入版本最多一次修正。旧任务保持原路线。最终全部页面实际查看后，用当前 output_revision 审核；交付说明对应实际路线，原图不套用模型推测，轮廓转描只保留可见外形。

修改 AGENTS.md、Skill 及运行协议时使用 writing-for-agents。旧手动任务沿用其来源约定，新任务不恢复手工选框主线。

运行仓库验证：

```sh
uv run --python 3.12 --quiet --isolated --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt python -m unittest discover -s tests -v
python tools/sync_skill_references.py --check
```

修改公开入口时更新 tests/test_public_contracts.py 的共同约束。验证使用已有测试和合成重放；声明、历史决定重放、真实生图及实际看图区分记录。真实来源和跨宿主验收由用户执行，无回执不宣称通过。保留来源实际 PTS、time_base、hash、修正预算和结果历史；未知成本保持 null。

匿名获取、公共地址/TLS 校验、资源期限、解码清理、输出不覆盖和来源完整性保护继续执行。只用合成标记测试脱敏，不读真实凭证。仓库有其他未提交工作时使用隔离工作区，保护用户修改和实验材料。远端写入须按用户明确授权，不自动 push、合并或关闭工单。

对外 Skill 为 skills/bilibili-drum-score-to-pdf/ 自包含目录。修改 docs/agents 的运行协议后执行 `python tools/sync_skill_references.py`，tests/test_skill_package.py 验证同步及仓库外运行。安装工具从已提交快照发布，更新前保留可恢复副本和未管理任务。

跨轮次续跑先读取 work/engineering/CURRENT.md，再核对 Git；交接格式见 docs/agents/engineering-handoff.md。旧协议与历史实现通过 Git history 查看，不把旧设计文档作为当前操作指引。
