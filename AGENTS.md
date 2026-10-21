# 项目工作约定

先读 docs/architecture.md 确认支持范围；验证命令及真实证据读 docs/verification.md；术语见 GLOSSARY.md。项目文档使用 google-developer-docs，unslop 润色。修改 AGENTS.md 时使用 writing-for-agents。

当前产品为 drum_score Python/CLI 与匿名网站。转换参数读 docs/script-product/conversion.md；网站状态、资源、清理和 schema 读 docs/script-product/website.md。旧 Skill、模型编排、重绘、矢量、MIDI 和人工批准协议已退役，历史实现经 Git history 查阅，旧任务不自动迁移。

同位置重叠去重，后续重复音乐保留。分页保持完整谱行、关键记号、原行距及统一比例。音乐不可读或配准歧义时说明失败，不猜隐藏符号。complete 只表示完整产物发布，始终 reliable=false。合成测试、固定决定重放、真实来源与实际看图区分记录，不冒称音乐校对。

修改公开入口时更新 tests/test_public_contracts.py 共同约束。先运行针对性合成验证，再按风险运行全回归及真实来源/全部页面验收。保留原始来源与派生区别、实际 PTS/time_base/hash、资源参数和失败证据；未知成本为 null。线上清理与实验留证分开。

匿名获取、公共地址/TLS、资源期限、进程树清理、输出不覆盖和来源完整性保护继续执行。安全测试仅用合成标记，不读取真实认证。删除旧测试前迁移其中仍适用的断言，并更新 docs/test-migration.md。实验、已安装 Skill、用户修改和未知文件保持原样。

数据清理仅作用于登记的受管身份。schema 未知时拒绝启动；恢复副本应核验后登记新 inode/ctime，原完成与期限不刷新。资源参数保持显式直接，不提前删除未到期结果。

独立环境安装开发及测试依赖后运行 `python -m unittest discover -s tests -v`，具体安装命令见 docs/verification.md。CI 使用同一测试和纯程序合成证据，不运行旧 Agent 批准重放。

跨轮次续跑先读当前工程交接 CURRENT.md，再核对 Git，格式见 docs/agents/engineering-handoff.md。GitHub Issues 位于 kenqia/bilibili-drum-score-to-pdf，远端读取核对 Git remote。远端写入按明确授权范围执行，不自动 push、关闭工单或合并。服务器与域名部署另行授权。
