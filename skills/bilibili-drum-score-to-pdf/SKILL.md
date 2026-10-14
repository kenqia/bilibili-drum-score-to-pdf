---
name: bilibili-drum-score-to-pdf
description: 将 B站链接或本地视频中的白底多行鼓谱粗拼、清理重绘并重排成完整 A4 PDF；明确要求时另导出 MIDI。
---

# 鼓谱视频转 PDF

用户给出 B站链接或本地鼓谱视频后，Agent 自行导航、审阅、重绘和逐页检查，交付以实际谱名命名的 PDF。使用本文件旁的 `scripts/convert.py`，通过本文件真实路径向上定位仓库根目录。先读仓库 `docs/agents/reconstruction-workflow.md`；调用参数见 `docs/agents/reconstruction-local.md` 和 `docs/agents/reconstruction-navigation.md`。

需要 Python 3.12+、uv、ffmpeg、ffprobe、原生图片查看能力以及 PDF 页面渲染工具，项目使用 Poppler。依赖在隔离 uv 环境中运行，不读取 B站 Cookie、登录态或模型认证。

```sh
uv run --isolated --with-requirements /absolute/repository/skills/bilibili-drum-score-to-pdf/scripts/requirements.txt \
  python /absolute/repository/skills/bilibili-drum-score-to-pdf/scripts/convert.py \
  'https://www.bilibili.com/video/BV1rH4y1R7Rk' --output /absolute/path/to/new-task
```

把 `/absolute/repository` 换成实际仓库路径。省略 `--operation` 使用新版 `prepare`；本地视频使用同一入口。链接支持 `?p=2`。准备只创建待审阅任务，不表示已交付。后续操作使用 `--task` 与 Agent 编写的 `--request` JSON，用户无需填写 JSON。完整操作列表和请求规则见 `docs/agents/reconstruction-entry.md`。

1. 准备任务后调用 `stage`，按响应的 `phase`、产物、检查、未决和 `next` 继续。正常来源自动采集、检查与冻结，生图前无需 Agent 复看。音乐、接续或裁剪未决时补采；未解决保留 blocked。
2. 按 `handoffs` 执行真实宿主生图或恢复已有 request。实际查看每个生成结果，核对音乐记号，提交完整行边界。每个输入版本最多一次定向修正；工具缺失、失败或修正后仍不合格时转矢量，轮廓转描不称为音乐识别。
3. 再调用 `stage` 导出 A4 和全部有序预览。实际查看最终每页，检查标题、顺序、首尾、关键记号、裁断、重叠和留白，用当前 output_revision 调用 `review-pdf`。只有 complete 才交付。

局部裁剪、A→B→A 额度恢复、重新分组、未知调用与仅改布局时，读取 `docs/agents/stage-recovery-layout.md`。低层来源异常操作读取 `docs/agents/automatic-source-checks.md` 和 `docs/agents/reconstruction-workflow.md`。
恢复时使用当前任务 `record.json`，验证来源和派生产物 hash 后复用有效截图、已接受生成图和修正预算。旧观察包、决定协议、auto/fast/full 模式及 `--operation convert` 已退出；不自动迁移旧任务。历史实现通过 Git history 查看，回滚使用独立 checkout 与新任务目录。

只有用户自然语言明确要求 MIDI 时才读取 `docs/agents/midi-conversion.md`，并加载可选 Mido。普通 PDF 任务不提供 MIDI 配置提示。完整音乐转写和导出回读独立于 PDF；MIDI 失败保留已审核 PDF。可靠门槛不满足时拒绝可靠交付；只有用户明确接受近似播放时才能执行 `midi-playable`，保留原转写、未决项、授权原话和应用假设，输出 `midi_playable`、`reliable=false`。文件可解析不证明音乐准确。

支持视频中已有的固定比例、白底多行鼓谱，向上推进或能确认有序翻页。没有谱面的演奏视频、横向滚动、比例变化或无法确认接续的布局不强行报完整。无视觉能力不能声称已看图；受控测试不计真实生图或音乐准确验收。未知模型成本保持 `null`。安全边界及实际验收见仓库 `docs/architecture.md`、`docs/verification.md`。
