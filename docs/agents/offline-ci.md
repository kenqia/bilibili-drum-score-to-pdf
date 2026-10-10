# 离线 CI 与保存决定重放

GitHub Actions 的 `Offline score verification` 在 PR、main 和 integration 分支 push 时运行，也支持手动触发。独立 Ubuntu 24.04 runner 使用 Python 3.14、仓库已固定的 requirements、ffmpeg、Poppler 和 DejaVu 字体。普通测试通过两个确定性 shard 覆盖完整 unittest discovery，固定决定 replay 使用独立 job。三个 job 各限时 15 分钟，不增加模型 SDK，也不读取模型凭据或 B站输入。分片命令与覆盖复核见[验证入口](../verification.md#离线-ci-分片与-15-分钟预算)。

仓库没有独立 lint、typecheck 或 build 命令，本 workflow 不编造这些门禁。当前 CI 只提供检查结果，未修改分支保护或 GitHub 设置。Issue #21 的其他 CI 要求继续由原票跟踪，本票不关闭或修改它。

## 本地复核

```sh
uv run --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt python -m unittest discover -s tests -v
uv run --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt python ci/verify_agent_replay.py --output work/ci-evidence
```

证据目录必须不存在。第二条命令只生成受控合成视频，使用固定决定提交，再通过统一 CLI 导出与重放。检查 3 条谱行、源 RGB 原裁剪像素、至少 150 effective DPI、1 页 A4 和两次 PDF 字节相等。负例验证未知协议、带越界坐标的观察包，以及已保存决定后损坏的原生图像。每个负例必须拒绝，不能留下被接受的非法决定或 PDF。

固定决定中 `visual_review=true` 是测试夹具的已审阅状态，模型标识为 `synthetic-fixture`。没有 Agent 实际看图。CI 重放成功只能证明决定执行、来源核验和导出行为，不能证明视觉识别正确。滚动、补采样、换页和恢复的后续实现分别维护自己的离线测试，完整 unittest 自动收录。

## 证据范围

Artifact 只包含 `summary.json` 和成功时的 `fixture-score.pdf`，总量小于 5 MiB，保存 7 天。summary 只记录受控夹具版本、验证结果、PDF hash 和有限失败类型/代码。未知异常不保存消息。输入路径、视频、task/observation/decision 原始记录、认证、URL、模型对话和原始 subprocess 日志均不上传。

受控负例的错误代码写入成功 summary。失败测试还移除子进程的 ffmpeg 搜索路径，确认失败 summary 不带路径或日志。replay job 与两个回归分片独立执行，回归失败不会跳过重放。replay 依赖安装失败或取消时可能没有 artifact；上传步骤对此报告 warning，不把缺少证据伪装成通过。

## 配置影响与回滚

新增 workflow 会消耗 GitHub runner 时间，并上传上述合成证据；每个 job 最多 15 分钟，两个回归分片使用 `fail-fast: false`，重复同分支运行会取消旧运行。权限只有 `contents: read`，checkout 不持久保存认证。依赖仅安装在临时 runner，不改开发机全局配置。Actions 引用按官方 tag 的 commit 固定，升级时重新核验。

回滚通过 revert 新增 workflow 的提交停止后续自动运行，历史运行与 artifact 按 GitHub 保存策略保留。本票没有旧 workflow 可覆盖，也没有更改认证、hooks、全局配置或 GitHub 设置。

## 验证边界

本地通过不代表 hosted runner 已通过。首次实际 GitHub 成功运行及 artifact 下载结果必须在发布集成分支后记录。联网获取、真实 Agent 视觉审阅、整曲覆盖、真实资源成本和实物打印仍需单独验收。

官方参考：[checkout](https://github.com/actions/checkout)、[setup-python](https://github.com/actions/setup-python)、[upload-artifact](https://github.com/actions/upload-artifact)。
