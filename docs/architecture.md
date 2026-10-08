# Moving viewport 架构与实施规格

Row identity is spatial, not pixel-content identity.

Geometry proves identity. Content may only veto obvious impossibility.

Prefer a clean real observation over reconstructing an occluded observation.

Partial rows are ignored until they become complete.

No pixel reconstruction in the normal product.

## 决策

将视频视为一张现成长谱的移动窗口。五线锚点、共同纵向位移与出现顺序建立谱行位置。每条打印谱行来自一个真实视频帧的完整无遮挡裁剪，只转灰度。标题与速度从首张稳定谱面独立保存。

从 `0b4da0639c51bf121bfa0574e456409b643936af` 开始重写。保留匿名获取和网络安全模块；几何跟踪、候选选择、搜索分别由三个小模块承担，总量限制为 500 行。现有生产核心在新路径真实验收通过后删除。历史实现保存在 Git 中。

## 几何契约

完整五线按屏幕位置排序。相邻窗口至少两个锚点有序重叠，其位移须在小于五线间距的容差内一致。比例或横向布局变化返回 `unsupported_layout`。向下移动、无重叠和多个同等合理的位移不强行接续。

累积 `scroll_offset += scroll_delta`，观察位置为 `global_y = staff_y + scroll_offset`。同位置观察归入已有 track，后续新位置建立新 track。重复段落按空间位置保留。

输入 `[300,500,700] → [100,300,500]` 若位移为 200，则三个 global_y 仍为 `[300,500,700]`，没有新行。要同时新增一行，新窗口需再出现锚点 700。测试分别验证共同位移与新行扩展，不能让示例的计数与坐标公式矛盾。

## 搜索与候选

从当前稳定观察逐步增大 seek 步长，发现推进后局部细搜。搜索保留至少两条旧完整行，并观察稳定位置。所有解码请求和实际完整画面分析计入 metrics。视频真实末帧单独核查。

完整性、光标、固定遮挡只决定候选能否打印。候选选择先过滤不完整或遮挡观察，再按锐度降序、时间升序选择。没有干净候选时只在该行已观察的时间范围补采少量帧，仍无可用观察则 `waiting/no_clean_observation`。不恢复像素。

## 输出与验收

只返回 `success`、`waiting` 或 `failed`。waiting 保存时间、截图及简单原因，用户提供更好的视频后运行新任务。manifest 保存来源、原帧、bbox、时间、global_y、所选原裁剪、打印位置和指标。

合成测试先验证几何与候选契约。真实验收使用 BV1rH4y1R7Rk，目标匿名 1080p、12 行、2 页 A4、标题速度完整、无光标、逐行来源精确一致，两次运行结果一致，完整画面分析少于 60 次。真实验收未通过不得合并。

## 限制与回滚

支持固定比例、白底、多行、单向向上推进且有足够重叠的长谱。稀疏采样无法证明两次观察之间没有换谱。等间距锚点在整行跳跃下可能不可辨认，须细搜或等待；内容不用于补足身份。

不新增生产依赖。回滚使用 Git 中的旧提交及新的结果目录，不能将旧任务状态当作新任务继续运行。远端提交、PR、合并及 Issues 修改需要单独明确确认。
