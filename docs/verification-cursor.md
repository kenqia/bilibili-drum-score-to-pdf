# 光标遮挡验证记录

2026-10-06，ticket #9。测试边界沿用统一 convert CLI、返回 JSON、证据文件、PDF 是否存在以及 resume CLI，没有直接测试私有比较函数。

修复前的四项光标基线运行 24.828 秒。三项既有用例通过，新反例失败：第一帧的小记号区域被光标覆盖，第二帧增加一个 5 像素黑点，CLI 仍返回 success、complete=true。它把两帧遮挡掩码的并集当作允许忽略的内容。另一个新反例先展示干净 A，再展示小点完全藏在不透明光标下的 A′，最后回到干净 A；旧实现也返回 success，单项红测 5.458 秒。这两次失败均来自错误的完整性声明，依赖和命令正常执行。

修复把掩码比较保留为候选归属，最终完成另需核对连续遮挡观察。它们必须保持同一 bbox，实际可见像素需一致，移动到不同位置的光标观察需互补覆盖全部隐藏区域，最后还必须与一张真实无遮挡整行吻合。固定位置的遮挡，即使两侧干净帧完全相同，也保留 cursor_occlusion。后续清晰帧不能清除已经积累的未证实观察。打印图始终取真实整行，不取累计比较掩码。

每行 observations 保存观察时间，cursor_recoveries 保存互补原图与实际清晰后帧，cursor_followups 保存不能自动确认的清晰后帧。等待疑点包含遮挡原图、时间和清晰 reference；质量报告把内容仍未证明的行列入 unrecovered_rows，即使所选打印候选本身没有光标。resume 不回答时继续 waiting，既有补图与接受缺失协议继续执行内容与状态校验。

互补观察只能证明已观察区域的一致性。它无法检测完全隐藏、随后消失的瞬时变化，也不能证明采样之间没有变化。允许移动光标视频完成仍依赖同位置谱面持续显示的条件；固定遮挡和不同位置归属不会使用这个条件自动通过。真实完整频道视频与实物打印未验收。

修复后五项光标 CLI 测试通过，31.318 秒，包含实际互补移动光标、浅色光标、两个内容反例及持续遮挡。两个既有光标恢复测试通过，22.659 秒，分别核查接受缺失后的定位和补图原始来源。四项邻接排序测试通过，29.212 秒，覆盖 ABCDA 重复段落、慢速滚动、无重叠和末尾残行。命令如下，完整仓库回归交由集成分支统一运行。

```sh
uv run --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt python -m unittest discover -s tests -p test_cursor_quality.py -v
uv run --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt python -m unittest discover -s tests -p test_resume_conversion.py -k cursor -v
uv run --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt python -m unittest discover -s tests -p test_ordered_conversion.py -v
```
