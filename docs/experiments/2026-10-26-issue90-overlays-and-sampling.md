# #90 覆盖物配准与采样对照

2026-10-26。候选从整合基线`28e8136a81d627a88b32bc9870bb62fb1ae28fb3`独立实施。只修改程序与网站，不修改独立Skill，不新增生产依赖。

## 决定与边界

保留0.5秒常规RGB默认。1秒和2秒确实减少本实验的存储与总耗时，但三档RGB均漏取0.1秒短驻留页。候选保留每个原生帧的128像素运动观察，并从原生变化峰值处补证。缩图阈值仍是启发式，尚不能承诺所有短页均被发现。

灰水印启动使用暗墨迹的严格唯一配准，保留至少三个独立非零位移和像素一致性要求。每帧高饱和度光标作为匹配未知区。所有匹配掩码均不修改输出像素；本票未恢复水印下的音符。

## 合成行为

`test_overlay_registration.py`先验证大灰水印使原检测得到0个独立比较，然后验证候选取得至少三个比较及正确的37像素位移。光标和高亮案例先复现`discontinuity`，候选得到零位移。

公开`convert`覆盖固定灰水印、随谱水印、移动彩色光标和无覆盖物对照。四种来源均保持450像素总位移，并逐像素保留首个实际视口。新短驻留反例在两个相同常规采样间插入实际编码的0.1秒不同画面，基线发布成功，候选明确`discontinuity`且不发布目录。基线red输出保存在下述实验目录的`native-short-red.txt`。

原有固定覆盖物、周期别名反例继续通过。背景闪烁仍需保留零位移谱面；它的实际补帧不具有常规采样间隔的运动摘要，因此既有最大变化断言只读取已记录的摘要。

## 实际采样

实验根为`/home/kenqia/my_folder/bilibili-drum-issue-90/work/engineering/2026-10-26-issue90/`。`sampling/comparison.json`记录每次实际解码的来源hash、区间、PTS/time_base、RGB字节和原生观察。来源来自既有`downloads.json`，没有重新下载。各档使用同一区间与600秒累计解码预算；完整转换使用600秒总期限及各1GiB临时空间和RSS额度。

| 情形与区间 | 间隔秒 | RGB帧 | PNG字节 | 采样秒 | 原生观察 |
| --- | ---: | ---: | ---: | ---: | ---: |
| M216滚动30..40秒 | 0.5 | 20 | 2486158 | 0.476 | 250 |
| 同源同区间 | 1 | 10 | 1241752 | 0.357 | 250 |
| 同源同区间 | 2 | 5 | 621736 | 0.326 | 250 |
| Xp翻页57..62秒 | 0.5 | 10 | 1264458 | 0.366 | 105 |
| 同源同区间 | 1 | 5 | 632264 | 0.311 | 105 |
| 同源同区间 | 2 | 3 | 380405 | 0.303 | 105 |
| 合成短驻留0..4秒 | 0.5 | 8 | 20664 | 0.080 | 40 |
| 同源同区间 | 1 | 4 | 10332 | 0.081 | 40 |
| 同源同区间 | 2 | 2 | 5166 | 0.083 | 40 |

这里未追加尾帧。三档完整转换均通过公开`convert`运行，独立实验`sitecustomize`仅替换既有采样器收到的间隔，不新增生产选项或成功标准。该覆写的实际间隔以实验顶层`interval_seconds`为准，内部默认值指标不用于解释覆写实验。

| 情形 | 0.5秒完整转换耗时 | 1秒 | 2秒 | 结果 |
| --- | ---: | ---: | ---: | --- |
| M216 30..40秒 | 6.661 | 5.497 | 3.484 | 三档均complete，reliable=false |
| Xp 57..62秒 | 3.587 | 3.283 | 3.480 | 三档均discontinuity，无结果目录 |
| 合成短驻留0..4秒 | 1.190 | 1.102 | 1.214 | 三档均discontinuity，无结果目录 |

实际查看三档完整预览后发现第25小节谱行在底部只露片段。三档预览SHA-256相同，为`08ac5c334c2d86211761581ebd2935803693c37e09e4b107e6d1b159f28f01ad`。这些`complete`只保留为状态与成本事实，谱面质量验收作废，不能计作#88真实通过；本候选尚未合入#89完整行保护。

M216三档分别保留21/11/6张RGB，包含尾帧；实际保留字节为2610557/1366151/746135，补帧量均为0。进程树采样RSS峰值分别为143876096/154525696/130510848字节，临时空间峰值为3031417/1782180/1159758字节。失败转换不公开资源摘要，故其实际峰值和补帧数记为`null`，不从成功来源推算。实验只各运行一次，不构成统计性能结论。

## 真实来源与实际看图

BV1JU4y1y7Zy候选v1公开转换运行23.080秒后返回`discontinuity`，没有PDF或预览可验收。只实际查看旧原生contact：约48.525秒从20附近跳至24/25附近，灰水印保留，不能凭静止水印把两个谱面放在同位置。既有500张原生采样的固定覆盖物检测仍未取得独立非零位移，遮罩为0；这项失败需要与无重叠翻页处理联合复核。不能将本票合成成功冒称JU完整真实通过，也没有水印下内容恢复的证据。

在生产整合worktree的原始28e8136上，同源完整M216公开转换20.348秒后也是`discontinuity`。证据为`M216-production-baseline.json`，来源hash为`downloads.json`记录的完整媒体hash。该失败是既有基线事实，不属于本票或#89新回归。

完整来源和所有页面验收留给后续整合候选。以上合成、实际采样、真实失败和旧图观察分开记录，未进行逐符号音乐校对。

## 验证命令

使用既有独立Python 3.12环境，`PATH`首项指向该环境的`bin`，`PYTHONPATH=src:tests`。最后一组针对性验证为：

```sh
python -m unittest discover -s tests -p test_overlay_registration.py -v
python -m unittest \
  test_script_conversion.ScriptConversion.test_short_unrelated_page_between_equal_samples_is_not_silently_dropped \
  test_script_conversion.ScriptConversion.test_gray_and_scrolling_watermarks_and_playback_effects_keep_source_pixels \
  test_script_conversion.ScriptConversion.test_changing_background_keeps_unambiguous_stationary_score \
  test_public_contracts.ScriptPublicContracts.test_selected_range_and_manual_region_reach_all_entries_and_retry -v
```

固定覆盖物原测试与原生周期别名测试也已单独执行。完整程序回归、离线重放及真实来源联合验收由整合候选执行，本票没有把针对性结果当作完整回归。
