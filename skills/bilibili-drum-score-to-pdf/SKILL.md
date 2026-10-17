---
name: bilibili-drum-score-to-pdf
description: 将 B站链接或本地视频中的白底多行鼓谱粗拼、清理重绘并重排成完整 A4 PDF；明确要求时另导出 MIDI。
---

# 鼓谱视频转 PDF

用户给出 B站链接或本地鼓谱视频后，Agent 自行导航、审阅、重绘和逐页检查，交付以实际谱名命名的 PDF。使用本文件旁的 `scripts/convert.py`，所有路径相对本文件所在的 Skill 根目录，不需要源码仓库。用户显式选择本 Skill 并只提供视频链接时，即按默认 PDF 流程执行；用户未指定输出位置时，在当前工作目录下创建新的独立任务目录，交付时报告 PDF 绝对路径；已有文件保持不变。

正常流程先读 `references/stage-recovery-layout.md`，调用参数见 `references/reconstruction-entry.md`。来源异常或需人工导航时，再读 `references/reconstruction-workflow.md`、`references/reconstruction-local.md` 和 `references/reconstruction-navigation.md`。

宿主发现或依赖检查运行 `scripts/host_check.py`；在隔离环境中使用 `uv run --quiet --isolated --with-requirements scripts/requirements.txt python scripts/host_check.py`。检查公开 Skill 入口、工具和依赖版本，宿主实际看图与生图能力另行确认。

需要 Python 3.12+、uv、ffmpeg、ffprobe、原生图片查看能力以及 PDF 页面渲染工具，项目使用 Poppler。依赖在隔离 uv 环境中运行，不读取 B站 Cookie、登录态或模型认证。

```sh
uv run --isolated --with-requirements "/absolute/skill/scripts/requirements.txt" \
  python "/absolute/skill/scripts/convert.py" \
  'https://www.bilibili.com/video/BV1rH4y1R7Rk' --output /absolute/path/to/new-task
```

把 `/absolute/skill` 换成本文件所在目录的绝对路径。省略 `--operation` 使用新版 `prepare`；本地视频使用同一入口。链接支持 `?p=2`。准备只创建待审阅任务，不表示已交付。后续操作使用 `--task` 与 Agent 编写的 `--request` JSON，用户无需填写 JSON。完整操作列表和请求规则见 `references/reconstruction-entry.md`。

1. 准备任务后调用 `stage`。默认先观察首尾及谱面布局，优先读取行首小节号，再根据已证明的新增完整谱行和重叠情况调整跳转，建立持久谱行清单。按 `phase`、检查、未决和 `next` 继续；单次导航预算用尽时继续 `stage`。普通视频不先运行全曲 `overview`。
2. 用 `row-manifest` 查看谱行顺序、逐行编号、来源及接续。数字不全或矛盾时暂停，实际看图后用 `review-row-anchors` 补充读数或授权有界替代证据；程序不能自行绕过缺号要求。唯一重叠和滚动关系可由程序判断；明确可读的小节顺序、完整行边界和首尾记号也可共同证明接续。实际看图后通过 `review-continuity` 登记编号依据，不伪造编号识别。原始接续疑点保留稳定身份，连续两次补采无收益就停止二分并交给 Agent，重启不重置次数；未解决的音乐、位置和裁剪问题保留 blocked。
3. 来源检查通过后选取合格来源并冻结粗拼。接续证据完整可以推进后续流程，严格时间覆盖单独记录；稀疏观察不能证明未采样时间没有短暂换谱。显式使用 `stage` 的 `mode=strict` 或 `overview` 执行连续扫描。程序冻结无需 Agent 额外复看全部粗拼。
4. 按 `handoffs` 执行真实宿主生图或恢复已有 request。`ready_to_dispatch` 先执行 `dispatch-redraw` 再调用宿主；`recover_existing_call` 先恢复结果。批量与作废规则见 `references/stage-recovery-layout.md`。实际查看每个生成结果，核对音乐记号，提交完整行边界。每个输入版本最多一次定向修正；工具缺失、失败或修正后仍不合格时转矢量，轮廓转描不称为音乐识别。
5. 再调用 `stage` 导出 A4 和全部有序预览。实际查看最终每页，检查标题、顺序、首尾、关键记号、裁断、重叠和留白，用当前 output_revision 调用 `review-pdf`。只有 complete 才交付。

局部裁剪、A→B→A 额度恢复、重新分组、未知调用与仅改布局时，读取 `references/stage-recovery-layout.md`。低层来源异常操作读取 `references/automatic-source-checks.md` 和 `references/reconstruction-workflow.md`。
恢复时使用当前任务 `record.json`，验证来源和派生产物 hash 后复用有效截图、已接受生成图和修正预算。旧观察包、决定协议、auto/fast/full 模式及 `--operation convert` 已退出；不自动迁移旧任务。历史实现通过 Git history 查看，回滚使用独立 checkout 与新任务目录。

只有用户自然语言明确要求 MIDI 时才读取 `references/midi-conversion.md`，并加载可选 Mido。普通 PDF 任务不提供 MIDI 配置提示。完整音乐转写和导出回读独立于 PDF；MIDI 失败保留已审核 PDF。可靠门槛不满足时拒绝可靠交付；只有用户明确接受近似播放时才能执行 `midi-playable`，保留原转写、未决项、授权原话和应用假设，输出 `midi_playable`、`reliable=false`。文件可解析不证明音乐准确。

支持视频中已有的固定比例、白底多行鼓谱，向上推进或能确认有序翻页。没有谱面的演奏视频、横向滚动、比例变化或无法确认接续的布局不强行报完整。无视觉能力不能声称已看图；受控测试不计真实生图或音乐准确验收。未知模型成本保持 `null`。运行与安全边界见 `references/support.md`；完整历史验收记录见项目仓库的 `docs/verification.md`，无需下载历史证据才能运行。
