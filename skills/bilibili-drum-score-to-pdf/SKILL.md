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

1. 低清导航定位主要谱面推进，保留必要的原生截图并实际查看。记录真实 PTS，分别计量低清探测、原生截图和实际呈交图像。确认视频首尾、重叠和有序翻页接续，不用稀疏样本声称没有漏谱。
2. 选取完整谱行及标题、速度、拍号、署名和行外记号，按原谱位置拼成粗拼谱。去掉同位置截图重叠，保留后续重复音乐。水印、播放矩形和高亮可留在输入；关键符号遮住或不可读时有目的地局部补采，不猜音符，不设置旧补采轮数限制。
3. 默认调用宿主实际可用的生图工具，参考粗拼输入清理重绘。每个图页最多一次定向修正，预算在调用前保存。工具缺失、失败或修正后仍不合格时，使用本地轮廓转描及补五线的矢量兜底。它不能恢复完全隐藏的符号，也不生成音乐语义。
4. 实际查看重绘输出，核对原谱音符、鼓谱符头、符梁、附点、装饰音、连音、力度、速度和首尾。确认输出中每个完整谱行的边界后导出。完整行等比例重排为 A4 竖页，自动计算分页，不能纵向拉伸记谱。
5. 渲染并实际查看最终每页 PDF，检查整曲顺序、关键记号、首尾、裁断、重叠和留白，再调用 `review-pdf`。有未决内容时保留问题，不报完整成功。当前交付位于 `exports/<revision>/<实际谱名>.pdf`；材料与任务记录留在任务目录。

恢复时使用当前任务 `record.json`，验证来源和派生产物 hash 后复用有效截图、已接受生成图和修正预算。旧观察包、决定协议、auto/fast/full 模式及 `--operation convert` 已退出；不自动迁移旧任务。历史实现通过 Git history 查看，回滚使用独立 checkout 与新任务目录。

只有用户自然语言明确要求 MIDI 时才读取 `docs/agents/midi-conversion.md`，并加载可选 Mido。普通 PDF 任务不提供 MIDI 配置提示。完整音乐转写和导出回读独立于 PDF；MIDI 失败保留已审核 PDF。可靠门槛不满足时拒绝可靠交付；只有用户明确接受近似播放时才能执行 `midi-playable`，保留原转写、未决项、授权原话和应用假设，输出 `midi_playable`、`reliable=false`。文件可解析不证明音乐准确。

支持视频中已有的固定比例、白底多行鼓谱，向上推进或能确认有序翻页。没有谱面的演奏视频、横向滚动、比例变化或无法确认接续的布局不强行报完整。无视觉能力不能声称已看图；受控测试不计真实生图或音乐准确验收。未知模型成本保持 `null`。安全边界及实际验收见仓库 `docs/architecture.md`、`docs/verification.md`。
