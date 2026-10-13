# B站鼓谱视频转 PDF

给视觉 Agent 一个 B站链接或本地鼓谱视频，Agent 将原谱截图粗拼，调用宿主生图清理重绘，必要时使用轮廓矢量兜底，再把完整谱行重排为 A4 PDF。交付文件使用实际核对的谱名。项目是 Agent Skill，没有内嵌模型 API，也不要求 B站 Cookie。

```text
请安装 https://github.com/kenqia/bilibili-drum-score-to-pdf 的
bilibili-drum-score-to-pdf Skill，保留完整仓库并按当前宿主注册。
请将 https://www.bilibili.com/video/BV1rH4y1R7Rk
中的完整鼓谱整理为 PDF，保存在我指定的目录。
```

安装方法见[安装指南](docs/install.md)。宿主需要文件读写、脚本运行、原生图片查看、PDF 页面查看能力。优先使用宿主已有生图工具，没有工具时使用矢量路线。每页最多一次定向修正；关键记谱遮挡时局部补采，不能补造音符。

当前验证范围是固定比例、白底多行、向上推进或可确认有序翻页的视频。横向滚动、无法确认接续及没有谱面的演奏视频不在支持范围内。准备任务和生成 PDF 不等于完成审核，Agent 必须实际检查每页。

明确要求 MIDI 时，Agent 才加载[独立转换流程](docs/agents/midi-conversion.md)。可靠音乐转写未通过时不宣称可靠；用户明确接受近似播放后可以得到 `midi_playable`、`reliable=false` 的整曲 MIDI，保留鼓件与节奏假设。PDF 和 MIDI 分别验收，MIDI 失败不丢弃已审核 PDF。

# 本地运行

需要 Python 3.12+、uv、ffmpeg、ffprobe 和 Poppler。入口使用新版截图与重绘流程。

```sh
uv run --isolated --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt \
  python skills/bilibili-drum-score-to-pdf/scripts/convert.py video.mp4 --output /absolute/new-task
```

此命令准备任务，Agent 继续导航、采集、选行、重绘、导出和逐页审阅。命令请求见[新版入口](docs/agents/reconstruction-entry.md)，完整操作见[Agent 工作流](docs/agents/reconstruction-workflow.md)。产物位于任务目录的 `exports/<revision>/<谱名>.pdf`。原视频、截图及来源记录保留，恢复检查 hash 后复用有效工作。

旧 moving viewport、干净原帧门禁、决定兼容层和旧模式已移除。旧任务不自动迁移；历史代码和文档通过 Git history 查看，回滚使用独立 checkout 和新任务目录。

# 验证

```sh
uv run --isolated --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt \
  --with mido==1.3.3 python -m unittest discover -s tests -v
```

[架构](docs/architecture.md)说明输入与来源边界，[验证记录](docs/verification.md)区分离线测试、真实生图、实际看图与近似 MIDI，[首发状态](docs/launch-readiness.md)记录当前范围。CI 只检查合成和确定性产物，不调用宿主模型。未知模型成本保持 null。
