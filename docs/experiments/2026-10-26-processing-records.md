# 整理记录与简介规则的本地验证

2026-10-26，按用户确认的[设计](../script-product/processing-records-design.md)实施。用户授权本地实现、审阅和提交，未授权 push、生产部署或生产数据读取。

## 范围和源码身份

本轮增加网站私有整理记录、心形简介规则、只读 JSON 导出、schema v4 及显式旧版本升级。CLI、Python 和独立 Skill 不启用网站简介规则。未新增生产依赖，未修改认证或机器配置。

工作区开始时已有另一任务的配准与分页改动。本轮以 `d31571a8864e66a0e4ff8586888fcbfea09b4bae` 为 Git 基线，按本轮修改单独暂存。混合文件中的既有改动不进入本轮提交；原实验、未知文件和用户修改保留。

证据位于 `work/engineering/2026-10-26-processing-records/`。Python 环境复用 `work/engineering/2026-10-23-parallel/venv312` 的 Python 3.12；测试设置 `PYTHONPATH=src:tests`，完整发现使用 `PYTHONPATH=src`，并将该环境 `bin` 放在 `PATH` 首位，数值库线程设为 1。

## 测试和故障证据

以下命令使用合成数据，不读取真实认证或生产日志：

```sh
python -m unittest test_processing_records -v
python -m unittest test_description_policy -v
python -m unittest test_maintenance -v
python -m unittest discover -s tests -v
python -m compileall -q src/drum_score
ruff check --select E701,E702 src/drum_score
```

完整工作区回归 247 项、229.733 秒全部通过，无跳过，证据为 `full.log`。该结果包含工作区已有的配准改动。另从 Git 暂存内容导出 `commit-tree/`，在没有其他未提交改动的目录运行 14 项关键测试，11.196 秒全部通过，见 `commit-tree-tests.log`。

准确暂存目录的 `python ci/verify_script_product.py --output …/ci` 离线重放通过，确认三行合成谱、全部预览、来源 hash、重复运行 PDF 字节相等及拒绝覆盖和输入预算，见 `ci.log`。这些验证不代表真实来源或音乐校对。

完整回归之后仅把维护 CLI 公共升级矩阵从 v1/v2 扩展为 v1/v2/v3，生产代码未变。该矩阵单独运行 1 项、1.761 秒通过，见 `upgrade-v3-cli-fixed.log`。两次早期针对命令误用了测试类名而加载失败，原日志保留，不能当作运行通过。

覆盖独立重试记录、链接规范化、能力凭据排除、日志和结果分别到期、额度不足不删未到期记录、拒绝事件、只读命令、备份恢复及显式 v3 升级。OS/SQLite 合成故障验证日志写入和 manifest 读取失败仍保留任务终态，阻止新操作，并在修复后保持原期限恢复记录。

简介验证运行真实独立 worker、元信息进程及合成外部传输。命中时未请求媒体，公开错误类别为通用 `unsupported_source`，内部记录保留具体原因和码点。相同来源的 CLI 仍可获取并转换。另覆盖短链正常解析及下载后预览失败，以及获取发布 fsync 失败，已知最终地址和简介检查信息均保留。完整字符表逐项检查，缺失简介及明确排除的表情放行。

项目没有配置静态类型检查器；编译检查不能替代类型检查。Skill 未改动，未运行独立 Skill 回归。

## 审阅与修正

需求轴发现下载后的处理失败丢失已知最终地址和简介规则信息，已修复普通失败及获取发布 I/O 失败两条路径并补回归。规范轴发现转换与日志磁盘预留未相加，以及日志专用 manifest 读取在故障隔离外，均已修复。两名只读审阅代理复核后关闭全部三项发现。

早期排版日志曾错误保存原转换设置，已修正为各次排版设置和输出摘要，实际 HTTP 回归通过。失败过程保留在 `public-records.log`，不将早期失败冒称通过。

## 打包验证与限制

首次从工作区打包时，旧 `build/lib` 缓存混入已撤回的 `youtube_backend.py`。该 wheel 已标记为 `.whl.invalid`，不用于交付。未删除原缓存，改从准确暂存目录重新构建；34 个包文件与该目录逐字节一致，不含撤回模块。

准确 wheel 的 SHA-256 为 `5b2fb7f4874d37f0adf0edef23eeaebe32ebfe7b973f9916a4e381921057ec2c`，见 `wheel.json`。在任务专用环境安装该 wheel，并通过任务本地 `.pth` 复用已安装的固定依赖。仓库外验证实际导入安装目录、JSON 导出、默认 604800 秒期限，以及 web、worker、maintenance 新参数入口通过，见 `installed-smoke.json`。这不是两套依赖完全隔离的安装验收。

本轮未获取真实鼓谱、逐符号校对、生产压测或部署。线上仍沿用既有发行；schema v3 生产根须另行获准后按维护流程备份、显式升级并切版。整个数据库或磁盘不可写时，仍无法保证所有终态记录落盘；日志缺口必须保留可见状态。
