# Issue #70 独立程序实施记录

2026-10-21，基线 `f30351f1b6c7a2185d233771c2d6952b2d711fde`。规格与输入版本由 Issue #69 的独立实验目录冻结；原附件未修改，SHA-256 为 `2ea5ddd758665efd48320d15e3be5c39706dd6dc290eb4e6dd738a75b87ee239`。本票保留旧产品。

## 实现与来源

新增 `drum_score.convert` 与薄 CLI。复用当前固定的 Pillow、NumPy、OpenCV、ReportLab、yt-dlp，未新增生产依赖。NumPy 2.5.3 要求 Python 3.12，因此可安装包声明 `requires-python>=3.12`。安装使用独立环境，不修改全局认证、配置或 Skill。

附件的分带 profile 与局部匹配代码保留来源 hash 和用户报告的使用许可，不推定原附件已有 MIT 许可证。删除产品路径中的全画布回跳策略，只按相邻画面累计原谱位置。保留实际 RGB，避免高色度过滤、全局变调与不确定遮挡修复抹掉记谱。完整谱行和无安全空隙的连续行组等比分页。

采样复用 `VideoReader` 记录实际 PTS/time_base，保留原生帧 hash、来源 hash、派生长图和实际 PDF 渲染的全部页面。发布使用私有同盘目录与原子排他目录改名，不覆盖已有输出。程序完成固定带未经音乐校对提示。

## TDD 与公开验证

测试边界沿用规格已批准的最高层转换入口，不新设内部算法测试边界。先写输入拒绝失败测试，随后实现输入及输出保护；CLI JSON 错误测试先失败于缺少入口，再实现适配。静态整链测试先失败于未实现转换；滚动测试首次因附件 worst-cell 判断被固定水印干扰而失败，修正为相邻分带匹配与二维重叠检查。

新增合成验收包括七行滚动首尾、不同位置相同音乐、原生无损彩色记号、PDF 中实际嵌入图像逐像素比对、完整有序预览及拒绝已检测的翻页。公开共同矩阵增加核心与 CLI；匿名获取复用现有 HTTP wire fixture，实际运行下载保护和转换，验证指定分 P 及私有媒体 DNS 拒绝。网络 fixture 不是新的真实下载验收。

已运行的专项验证：

```sh
PYTHONPATH=src:skills/bilibili-drum-score-to-pdf/scripts uv run --no-project --python 3.12 --isolated \
  --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt \
  python -m unittest discover -s tests -p test_script_conversion.py -v
```

首轮七项通过。相同环境的 `test_public_contracts.py` 19项与 `test_api_acquisition.py` 9项通过。`uv build --wheel --out-dir /tmp/issue70-wheel` 成功；从 `/tmp` 以 `uv run --no-project --isolated --with WHEEL drum-score ...` 实际完成合成视频转换，导入位置为安装后的 site-packages，无源码目录依赖。

收尾补充合成测试验证无安全空隙的超高连续行组：黄色记号贯穿两组五线时，公开转换保留一页和完整内嵌像素，不按灰度阈值切断浅色记号。核心与 CLI 的共同矩阵同时验证成功产物包含全部预览、来源不变和 `reliable=false`，无谱黑场返回 `unsupported_layout` 且不发布输出。恢复后实际复跑 `test_script_conversion.py` 8项，5.027秒，及 `test_public_contracts.py` 20项，28.792秒，均通过。该记录没有将新增测试声称为新的真实音乐验收，也没有声称完整回归已经运行。

## 初次优化版真实对比

固定输入版本2包含原三条和额外映射成功的《鲜花》。原三条来源 hash 没有改变。`optimized-first` 为开发中首轮候选，版本标签 `issue70-working-v1`，没有冒充不可变发布版本。比较由父任务工具以240秒、1400MiB进程树边界串行执行，排除下载和人工查看；RSS 每50毫秒采样，不是 cgroup 精确峰值。

| 输入 | 结果 | 时间 | 采样进程树峰RSS | 页数 |
| --- | --- | ---: | ---: | ---: |
| KiLLKiSS | 成功 | 152.88s | 244682752 bytes | 3 |
| 标准曲 | `decode_failed` | 60.63s | 207507456 bytes | 未发布 |
| 小星星 | 成功 | 34.51s | 209408000 bytes | 1 |
| 鲜花 | 成功 | 178.22s | 228208640 bytes | 3 |

标准曲失败保留在报告中，未改样本或放宽期限。根因为逐帧原生PNG默认压缩阻塞采样，撞到现有 VideoReader 单次60秒边界。后续改用低压缩无损PNG，并先检查几乎未移动的相邻帧，再执行广范围配准。必须复跑全部固定四条，不能只重试落败样本。

实施者实际查看 KiLLKiSS 全部3页，可见标题署名、34个五线谱、首尾1至135和两处连续分页，未发现明显缺行或裁断；首行蓝色播放记号和水印仍保留。该查看不是逐符号音乐校对，也不是用户验收。其他输出的实际逐页查看和后续测量需分别记录，不把几何或合成结果当作真实视觉批准。

原始证据位于本机 `/home/kenqia/issue69-context/evidence/`，不是仓库可移植数据。完整回归、服务器2GB预算及用户质量回执尚未在本条记录中声称完成。
