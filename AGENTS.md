# 项目工作约定

架构与支持范围读取 docs/architecture.md，验证入口和实际验收读取 docs/verification.md，领域术语见 GLOSSARY.md。文档使用 google-developer-docs 编写，unslop 润色。

正常 PDF 任务使用 `prepare → stage`。Agent 查看原生首尾画面，按可见接续补采，present 后 assemble 有序完整谱行；一份具体来源审阅覆盖标题、首尾和跨截图接续。来源未决保持待审，裁剪问题只针对实际报错或看图发现的区域修正。同位置只选择一个来源，不同位置的重复音乐保留。记号交错时保留连续行组。

命令字段读取 docs/agents/reconstruction-entry.md；局部修改、生图恢复、一次修正预算和打印布局读取 docs/agents/stage-recovery-layout.md。宿主生图优先，失败、不可用或确认无法恢复的未知调用转矢量。轮廓转描只保留可见外形。最终全部页面实际查看后，使用当前 output_revision 审核。

运行仓库验证：

```sh
uv run --python 3.12 --quiet --isolated --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt python -m unittest discover -s tests -v
python tools/sync_skill_references.py --check
```

修改公开入口时更新 tests/test_public_contracts.py 的共同约束。验证使用已有测试和合成重放；声明、历史决定重放、真实生图及实际看图区分记录。真实来源和跨宿主验收由用户执行，无回执不宣称通过。保留来源实际 PTS、time_base、hash、修正预算和结果历史；未知成本保持 null。

匿名获取、公共地址/TLS 校验、资源期限、解码清理、输出不覆盖和来源完整性保护继续执行。只用合成标记测试脱敏，不读真实凭证。仓库有其他未提交工作时使用隔离工作区，保护用户修改和实验材料。远端写入须按用户明确授权，不自动 push、合并或关闭工单。

对外 Skill 为 skills/bilibili-drum-score-to-pdf/ 自包含目录。修改 docs/agents 的运行协议后执行 `python tools/sync_skill_references.py`，tests/test_skill_package.py 验证同步及仓库外运行。安装工具从已提交快照发布，更新前保留可恢复副本和未管理任务。

跨轮次续跑先读取 work/engineering/CURRENT.md，再核对 Git；交接格式见 docs/agents/engineering-handoff.md。旧协议与历史实现通过 Git history 查看，不把旧设计文档作为当前操作指引。
