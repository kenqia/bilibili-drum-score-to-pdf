# 网站专家 v6 兜底验证

2026-10-29，按用户确认的[接入边界](../script-product/expert-fallback-design.md)，保留首选算法，增加默认网站任务的专家兜底。本次仅集成本地 `main`，未推送或部署。48 源效果验收尚未执行。

## 代码与来源

基线为 `4f70b09acdfc1b5795d9d841812be5f20b5f1b14`，最终产品代码为 `2a30c2fd134df4be8601034207dba6fbf0888573`。后续验证文档提交不改动产品或测试。实现工作区为 `/home/kenqia/my_folder/bilibili-drum-expert-v6-fallback`，本页所列本地证据均在该目录的 `work/engineering/` 中。

附件由用户通过 ChatGPT 网页版专门生成，用户接受将源码纳入仓库。ZIP SHA256 为 `45774f153955b9c74667b8a9bf4271ac1caf0055bff52ed693bac138131d62e1`。八个原模块的非 import 语法树与附件一致，来源和原文件 hash 保存在 `src/drum_score/expert_v6/ORIGIN.json`。改动仅涉及相对导入和 PDF 后端，不修改提取、匹配、排序、去重或裁剪算法。

PDF 后端使用已有 ReportLab，保留原包整数 A4 尺寸、图块几何和分页。灰度按相同通道值嵌入 RGB，以兼容现有临时打印排版。未新增生产依赖，不启用 OCR。专家灰度增白和颜色融合按用户确认原样保留。

仅网站归一化默认选项、首选 `unsupported_layout` 或 `discontinuity` 允许兜底。原成功路径和 Python/CLI 保持首选算法。兜底复用已下载文件及同一个受监督进程，不刷新预算或期限。结果始终 `reliable=false`，显示待复核警告。

## 验证命令与结果

使用已有 Python 3.12.12 环境，完整回归 302 项、468.244 秒全部通过，无跳过，进程退出码为 0。日志为 `full-regression-resumed.log`，命令如下。

```sh
PYTHONPATH=src:tests OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
  /home/kenqia/my_folder/bilibili-drum-score-to-pdf/work/engineering/2026-10-23-parallel/venv312/bin/python \
  -m unittest discover -s tests -v
```

专项验证和准确发行检查通过，证据如下。

| 验证 | 结果与本地证据 |
| --- | --- |
| 原包与 PDF 适配 | `tests/test_expert_v6.py` 覆盖原模块语法树、实际 PDF 嵌入像素、坐标和分页、原裁剪规则、真实工具包合成执行、临时排版、路由排除与首选成功产物不变。 |
| 实际网站链路 | `cached-expert-compatible.log` 验证实际专家引擎、PDF/全部预览、警告、缓存两任务仅下载一次、原缓存期限、临时排版、处理记录及 backup/verify/restore 后状态和 PDF 保持。 |
| 取消与总期限 | `test_website_expert_fallback_shares_cancellation_and_total_deadline` 在合成阻塞专家及真实子进程处确认进入阶段，验证进程树停止且无结果发布。 |
| 反向路由检查 | `routing-mutation.log` 在内存中将条件 `and` 改为 `or`，产生预期的 12 个失败，证明排除断言能够发现错误。未修改源码。 |
| 离线 CI 重放 | `ci-compatible/summary.json` 为 passed，三行一页，重复 PDF 相同，拒绝覆盖和资源超限。 |
| 准确发行 | `release-compatible/release-identity.json` 记录 commit、wheel/sdist 和 54 个包文件 hash；`final-source-verification.json` 再核对全部文件与制品。 |
| 仓库外安装 | `installed-compatible-smoke.json` 记录实际安装包导入、HTTP/worker 专家转换、下载 hash、临时排版、快照往返及原状态/期限保持。安装自身 wheel 使用 `uv --no-deps --target`，未安装额外运行依赖。 |
| 浏览器 | `browser-check/result.json`、`desktop.png` 和 `mobile.png` 记录 1280×1100、390×844 的警告、已加载预览、高级选项范围提示及无 console error；截图已实际查看。Chrome DevTools MCP 不可用，使用已有 Chromium 和直接 CDP。 |
| 静态检查 | `ruff check --select E701,E702 src/drum_score`、新代码语法编译、`node --check src/drum_score/static/app.js` 和 `git diff 4f70b09 HEAD --check` 通过。未配置静态类型检查器。 |

wheel SHA256 为 `eb40a5ed65c6e374844ba7dbd3c6bf31a58e11a9c23cc83c68b44c38d78573ed`，sdist SHA256 为 `51fd27330629a5eec48303373a8c0fe00589265eb8b689844c9e46d4bb9f9048`。发行构建使用 `tools/build_release.py`；离线重放使用 `ci/verify_script_product.py`。仓库外安装在 `/tmp` 执行，避免误用源码导入。

## 审查与失败记录

规范与需求两轴审查完成。规范审查发现的 P1 是任务摘要额外增加顶层 `expert` 后，旧维护工具严格比对 manifest 摘要而拒绝快照。最终将详细专家证据保存在 manifest 和私有处理记录，任务摘要沿用既有 `conversion` 与 `warnings`。`maintenance.py` 与基线逐字节相同，准确安装版快照往返通过。

`snapshot-red-v2.log` 保存该 P1 复现，后续绿色与 compatible 日志保存修复验证。首次快照夹具的非法 `min_free_bytes=0`、记录选择和合成阻塞器缺少导入分别属于已修复的测试问题。早期深色外框合成视频被原包拒绝；后续白底合成视频真实生成三行一页，未据此修改算法。

`full-regression-v1.log`、`full-regression-final.log` 在兼容性修复期间主动中止。`full-regression-compatible.log` 在跨轮次恢复时进程已不可用且缺少最终汇总，也不计为通过。最终完整结果使用 `full-regression-resumed.log`，不把这些中断记录冒称成功。

## 48 源与验收限制

`corpus-48.json` 标记为 `prepared_not_run`，包含 S01–S20、F01–F20 和原八源，不含此前跳过的 r9。40 例的旧本地媒体路径不可用，保留 URL 与来源 hash；八源本地视频仍可用。效果测试应走网站 worker，CLI/Python 不触发兜底。

本次合成结果不证明真实视频的完整性或音乐正确性。历史原包九源测试曾发现重印、缺行和尾部遗漏，不能把无自动裁剪警告解释为通过。本轮没有执行真实 48 源、独立 Skill 回归、Windows CI、目标机容量或生产验收。

## 本地集成与回退

本地 `main` 使用独立工作区 `/home/kenqia/my_folder/bilibili-drum-main`。先快进至基线，再通过单个 `--no-ff` 合并接入分支。原脏工作区、其他开发分支及实验资料保留。

效果不接受时，在干净的 `main` 工作区执行 `git revert -m 1 <本次合并提交>`，核对 `src/drum_score/` 与 `pyproject.toml` 恢复基线并运行针对性验证。基线另保存本地 tag `pre-expert-v6-20261029`。此操作撤销代码，不删除已有结果或刷新期限。推送和服务器切版分别需要明确授权。
