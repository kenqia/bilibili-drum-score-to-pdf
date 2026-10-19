---
name: bilibili-drum-score-to-pdf
description: 将 B站链接或本地视频中的白底多行鼓谱粗拼、清理重绘并重排成完整 A4 PDF；明确要求时另导出 MIDI。
---

# 鼓谱视频转 PDF

用户给出 B站链接或本地鼓谱视频后，Agent 自行导航、审阅、重绘和逐页检查，交付以实际谱名命名的 PDF。使用本文件旁的 `scripts/convert.py`，所有路径相对本文件所在的 Skill 根目录，不需要源码仓库。用户显式选择本 Skill 并只提供视频链接时，即按默认 PDF 流程执行；用户未指定输出位置时，在当前工作目录下创建新的独立任务目录，交付时报告 PDF 绝对路径；已有文件保持不变。

正常流程先读 `references/stage-recovery-layout.md`，调用参数见 `references/reconstruction-entry.md`。来源异常或需人工导航时，再读 `references/reconstruction-workflow.md`、`references/reconstruction-local.md` 和 `references/reconstruction-navigation.md`。

宿主发现或依赖检查运行 `scripts/host_check.py`；在隔离环境中使用 `uv run --python 3.12 --quiet --isolated --with-requirements scripts/requirements.txt python scripts/host_check.py`。检查公开 Skill 入口、工具和依赖版本；runtime_ready/prerequisites_ready 仅表示依赖就绪。显式 --probe-decode 运行有限时、无网络的合成解码探测，宿主实际看图与生图能力另行确认。

需要 Python 3.12、uv、ffmpeg、ffprobe、原生图片查看能力以及 PDF 页面渲染工具，项目使用 Poppler。依赖在隔离 uv 环境中运行，不读取 B站 Cookie、登录态或模型认证。

匿名下载遇到代理 CONNECT 403 或视频网页 HTTP 412 时，程序会在原期限内尝试一次公开 API 直连恢复，不修改宿主代理配置。恢复仍失败时读取脱敏诊断；不要自行加载 Cookie、改代理或重复编写下载补丁。具体边界见 `references/support.md`。

```sh
uv run --python 3.12 --isolated --with-requirements "/absolute/skill/scripts/requirements.txt" \
  python "/absolute/skill/scripts/convert.py" \
  'https://www.bilibili.com/video/BV1rH4y1R7Rk' --output /absolute/path/to/new-task
```

把 `/absolute/skill` 换成本文件所在目录的绝对路径。省略 `--operation` 使用新版 `prepare`；本地视频使用同一入口。链接支持 `?p=2`。准备只创建待审阅任务，不表示已交付。后续操作使用 `--task` 与 Agent 编写的 `--request` JSON，用户无需填写 JSON。完整操作列表和请求规则见 `references/reconstruction-entry.md`。

1. prepare 后调用默认 `stage(mode=agent)`，读取已有截图、首尾采样建议和请求模板。默认不启动 sparse/strict。Agent 用 navigate/capture/promote 获取来源，实际查看原生图后 present，再以明确 position 调用 assemble。
2. 来源审阅保留标题、音乐起点、末行和每个相邻谱行的结构化 evidence。没有编号时使用其他可见依据，不猜编号或隐藏符号。同位置由 Agent 明确选择更好来源，不同位置的重复音乐保留。source-issues 中的旧自动疑点逐项登记处理依据；音乐、裁剪、位置和引用完整性门禁继续执行。字段见 references/stage-recovery-layout.md。
3. 再调用 stage 验证冻结和 crop-checks。合法来源不重新扫描。显式 mode=sparse/strict 分别保留稀疏导航与连续扫描，不混写其 provenance 和覆盖范围；这些模式的编号与局部恢复规则见 references/automatic-source-checks.md。已有合法人工冻结未改来源时恢复，改变来源后按新契约补充受影响位置和接续证据。
4. 按全部 handoffs 执行真实宿主生图或恢复已有 request。ready_to_dispatch 先 dispatch-redraw 再调用宿主；recover_existing_call 先恢复已有结果，不能重发。实际查看每个生成结果并提交完整行边界；每组每个输入版本最多一次修正。无生图工具时先 redraw-inputs，再对每组 fail-redraw(outcome=unavailable) 留下理由，不伪造调用。轮廓转描不能称为音乐识别。
5. stage/export 导出 A4 和全部有序预览。实际查看最终每页，检查标题、顺序、首尾、关键记号、裁断、重叠和留白，用当前 output_revision 调用 review-pdf。只有 complete 才交付。CLI 可选 --summary，但必须从 details.path 读取完整回执材料，摘要不能代替实际看图。


局部裁剪、A→B→A 额度恢复、重新分组、未知调用与仅改布局时，读取 `references/stage-recovery-layout.md`。低层来源异常操作读取 `references/automatic-source-checks.md` 和 `references/reconstruction-workflow.md`。
恢复时使用当前任务 `record.json`，验证来源和派生产物 hash 后复用有效截图、已接受生成图和修正预算。旧观察包、决定协议、auto/fast/full 模式及 `--operation convert` 已退出；不自动迁移旧任务。历史实现通过 Git history 查看，回滚使用独立 checkout 与新任务目录。

只有用户自然语言明确要求 MIDI 时才读取 `references/midi-conversion.md`，并加载可选 Mido。普通 PDF 任务不提供 MIDI 配置提示。完整音乐转写和导出回读独立于 PDF；MIDI 失败保留已审核 PDF。可靠门槛不满足时拒绝可靠交付；只有用户明确接受近似播放时才能执行 `midi-playable`，保留原转写、未决项、授权原话和应用假设，输出 `midi_playable`、`reliable=false`。文件可解析不证明音乐准确。

支持视频中已有的固定比例、白底多行鼓谱，向上推进或能确认有序翻页。没有谱面的演奏视频、横向滚动、比例变化或无法确认接续的布局不强行报完整。无视觉能力不能声称已看图；受控测试不计真实生图或音乐准确验收。未知模型成本保持 `null`。运行与安全边界见 `references/support.md`；完整历史验收记录见项目仓库的 `docs/verification.md`，无需下载历史证据才能运行。
