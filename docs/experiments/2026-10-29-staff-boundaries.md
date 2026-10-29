# 谱行边界试做

2026-10-29。本轮完成候选实现与反例验证，未解决 S12、S14 的真实分行问题。
代码在本地 `codex/staff-boundaries`；基线为 main `adbcbb0247eff8656698e7e95345af96a94a4840`。
不合入 main，不 push，不部署。原脏工作区和此前 48 源交付保持原样。

## 范围与实现

仅修改程序/网站的谱行边界与打印布局，不改 Skill、获取、配准、拼接、去重或专家包算法。
复用既有 OpenCV、NumPy、Pillow、ReportLab 与 Poppler，没有新增依赖。
OpenCV 八连通标签记录几何组件；该 API 不提供音乐归属证据，参考[官方组件文档](https://docs.opencv.org/5.0/main_modules/imgproc_shape.html)。

`staff_boundaries.py` 分离检测图与交付 RGB，保存逐列路径；只在原合并组内部探测。
实际均匀灰边和受尺寸/亮度限制的小灰岛只在检测时排除，原像素交付仍保留。
组件被五线核心锚定时，允许有界空白路径；有游离实质记号则拒绝猜归属。
原有水平边界不变，超资源预算回退原组。
转换 manifest 增加 `pagination`，保留大组时增加 `joined_staff_rows` 警告；详细字段不写入持久 API 摘要或数据库。

本实现只具备合成几何证据。在当前 20 源分析中，所有分组数量和最大组行数与原算法相同，没有获得真实效果改善。
不能把合成测试通过写成用户问题已解决。

## 候选与失败

工程资料位于本地工作区 `work/engineering/`，所有旧目录保留：

| 目录日期均为 2026-10-29 | 实际结果与限制 |
| --- | --- |
| `staff-boundaries` | 初版可使 S12 最大 13→3、S14 最大 35→2，但实际第一页发现开镲圈、段落框、手法文字错行。拒绝采用。 |
| `staff-boundaries-attempt2` | 小型组件按最近墨迹归属，S12/S14 仍合并；扩大适用范围会引入错行风险。 |
| `staff-boundaries-final` | 全宽空隙结合小灰岛绕行，S12 最大 13→8、S14 最大 35→5；最长空白中点把下行上方圆圈留给上行。拒绝采用。 |
| `staff-boundaries-reviewed` | 优先最早空隙；对应真实图有所改善，但上行下方 `mf` 反例会被分到下行。拒绝采用。 |
| `staff-boundaries-safe` | 当前保守代码的 20 源纯分组分析，未重新生成 PDF。S12 最大 13、5 组；S14 最大 35、1 组，主问题未解决。 |

前三种策略各重排过 S01–S20，逐份比较全部 PDF 嵌入图片的非白 RGB 计数，计数相等。
这只能证明像素没有丢失、复制或改色，不能证明符号跟随正确谱行。
实际查看范围包括不同候选的 S12/S14 第一页及 S14 局部原图，没有完成全部页面的逐符号审阅。

输入来自此前 PDF 内嵌图片，非本轮视频获取或完整转换。
S12/S14 无间隔恢复 PNG 的 hash 与原 manifest 一致；其他样本只称保留 PDF 图片重排。
没有宣称恢复其他样本已删除的原始长图。
每次布局实际秒数保存在对应 `layout-replay.json`；当前分析秒数保存在 `staff-boundaries-safe/current-analysis.json` 和 `20case-analysis.json`。
这些耗时不包含视频获取、解码和拼接，不能称完整整理时间。

供用户查看的独立 Windows 导出为 `D:\迅雷下载\DrumScore_StaffBoundary_Experiments_20261029\index.html`，另有同名 ZIP。
首页和每份候选页面均明确标为未通过；原 48 源导出未覆盖。

## 保护反例

新增 `tests/test_staff_boundaries.py` 用真实 PDF 嵌入像素验证：

- 均匀灰边和交错浅灰点不再否决合成谱面的全部边界，源图不变。
- 已锚定且纵向交叠的两个符干可分开，原颜色、水平坐标与完整形状保留。
- 跨切口的 5 像素浅灰岛通过绕行完整留在一侧。
- 游离段落框、手法文字、小黑点、上下伸展符干附近的同基线 `R R L`、上行下方 `mf` 及下行上方圆圈保留组。
- 黄色、浅灰、浅彩色的真实跨行连接，以及非均匀边缘记号不被拆开。
- 分析资源和曲线填白预算不足时保留原组。

公开共同契约新增真实 Python/CLI/HTTP 转换及临时重新排版，验证合成分行、`reliable=false`、持久摘要不含 `pagination`、重排不改变任务状态。
独立审阅还发现并已修复：重复中位数计算导致计数二次增长；曲线外框填白使 1900 万原像素膨胀到 2346.4 万，超过提取预算。
修复后同一上限反例回退原组；400 行纯分组计数从审阅测得约 1.475 秒降至约 0.0096 秒。
这些基准不等同于完整转换性能。

## 验证命令与状态

程序 Python 使用既有独立环境的 Python 3.12.12，未新增安装。
在仓库根目录把其 `bin` 加入 PATH 后运行：

```sh
python -m unittest discover -s tests -p test_staff_boundaries.py -v
python -m unittest discover -s tests -v
python ci/verify_script_product.py --output work/engineering/2026-10-29-staff-boundaries-safe/ci-evidence
python -m compileall -q src/drum_score tests ci tools
```

针对性 8 项通过。新代码编译、变更文件 E701/E702 检查和 `git diff --check` 通过。
完整程序回归 311 项、445.748 秒，310 项通过、1 项基线失败，失败复现见下节。
离线 `ci/verify_script_product.py` 通过，三行合成谱、确定性 PDF 重放、输出不覆盖及资源拒绝均符合预期。
变异验证临时禁用游离记号保护，测试失败；从副本按原字节恢复并核验 hash 后，针对性 8 项再次通过。
日志分别位于 `staff-boundaries-reviewed/full-unittest.log`、`staff-boundaries-safe/ci-evidence/summary.json`、`mutation-result.json`、`targeted-after-restore.log`。
没有声称新 wheel、远端 CI、服务器或新一轮 48 源完整转换已验证。

## 后续决策

当前实验表明：知道五线位置和保全连通组件仍不足以证明独立记号归属。
不能把“所有像素还在”或“页数更多”作为验收成功。
后续可继续寻找可验证的自动归属证据，或另行明确人工边界/视觉辅助的范围。
本轮未自行增加生产模型依赖或人工标注界面。

### 环境与基线失败

完整回归中 `test_processing_records.ProcessingRecords.test_local_cli_exports_records_without_creating_missing_data_roots` 失败，CLI 返回 `records_unavailable`。
随后在本分支和未修改 main 上分别单独运行同一测试，两边均失败。
本轮未修改整理记录实现，不将该基线问题并入分行改动，也不把完整回归称为全绿。

一次 `python -m pip wheel --no-deps --no-build-isolation .` 尝试因现有程序环境未安装 pip 立即失败，没有构建或安装产物。
未为此修改环境。后续准确发行必须使用项目 `tools/build_release.py --commit ...`，本轮未执行发行验收。
