# 纯脚本转换首轮对照

2026-10-21。对应规格 #69、核心 #70 与资源验收 #71。本轮在 main `f30351f1b6c7a2185d233771c2d6952b2d711fde` 建立隔离集成分支，不修改用户原工作区、原附件、历史任务或已安装 Skill。尚未进行网站开发、服务器验收或远端写入。

## 固定输入与程序

初版固定集为以下三条已有本地全曲视频。重新计算 hash 并通过 ffprobe 读取媒体参数，没有重新下载。

| 输入 | BV | 时长，秒 | SHA-256 |
| --- | --- | ---: | --- |
| KiLLKiSS | BV15crrYUEPA | 208.966 | `3137c5881ec628872d5424ed42991f9156a1808964616a8d391e376e9132c2eb` |
| 可惜没如果，新版 | BV1rH4y1R7Rk | 298.600 | `80f9a8d19515cf624d7d13c27ea758e88118fddb4341fa06deaad040272877fe` |
| 小星星，另一位作者 | BV1np421S78S | 63.756 | `5f9ca93dd01b857562bcc25fe30e7570340b28a80a64565869ae5995bf99d79b` |

原附件 `video2pdf.py` 为33474字节，SHA-256 `2ea5ddd758665efd48320d15e3be5c39706dd6dc290eb4e6dd738a75b87ee239`。它由用户的朋友编写，用户报告已取得使用同意。此事实不构成新增许可证条款。以原文件默认参数运行，未改附件。

用户随后指出桌面“鼓谱”目录中的历史成品不错。盘点20份、55页，均为纵向A4。它们包括位图、无内嵌图及历史模型生成路线，不能用来证明新的纯脚本转换已达到相同质量。三条固定集对应成品与 #58 历史最终版本的 hash 不同，不能混称同一版本。

《鲜花》桌面成品与本地任务 output hash 精确一致，找到对应全曲视频。第二版清单保留原三条，追加335.32秒的 `BV1Yw4m1Y7YH`，视频 SHA-256 `9f948b7c4eca5c4e981baa2ca37563108393b37b1323b7008eafa8468b19947d`。首版清单及已运行结果保持原样。新增样本也须同时运行两条基线及优化程序。

## 运行边界

`tools/compare_script_core.py` 在运行前复核全部输入 hash、原附件 hash或 main HEAD，每次建立新结果目录，串行执行任务。子进程组默认有600秒期限和2048 MiB采样RSS上限；结束时清理该进程组。数值库线程限为1。额外的全部PDF预览由 pdftoppm 生成。

main 对照提取该提交的自动 `prepare`、`stitch` 与 `_continuous_pages` 算法，以原来的裁剪嵌图方式渲染PDF。它不经过旧产品的完整CLI交付，不创建虚构的长图或PDF批准，材料明确标记 `unreviewed_algorithm_extraction`。因此这里只比较其自动算法，不将它称为旧产品无人值守成功。

附件采用原CLI默认参数，`-o` 与 `--debug` 均指向全新目录。它的 register.tsv 时间是帧序号除帧率的估计，没有原生PTS记录。main保存实际PTS、time_base与原帧；派生长图不标为原生截图。

时间统计是本地程序执行时间，排除下载、人工查看及包装器额外渲染的PDF预览。附件自己的中间图/调试页生成包含在程序时间内，main包含原生端点及行裁图保存，二者工作量不完全相同。首版 measurement.json 的 `timing_boundary` 文本误写包含preview，数值实际不包含包装器额外预览；保留原件，此处纠正。之后工具单列 `extra_pdf_preview_seconds`。

内存为每50ms读取进程组各进程RSS的合计最大观察值，会重复计算共享页，也可能漏掉短时尖峰。它不是cgroup测得的严格峰值，不能直接作为2GB主机放行依据。运行办法依据 [Python 3.12 subprocess](https://docs.python.org/3.12/library/subprocess.html)，资源控制限制参见 [Python 3.12 resource](https://docs.python.org/3.12/library/resource.html)。本机为WSL，不是目标服务器。

## 首轮测量

| 输入 | 程序 | 程序秒数 | 采样进程组RSS，MiB | 页数 | PDF字节 |
| --- | --- | ---: | ---: | ---: | ---: |
| KiLLKiSS | main自动算法 | 15.100 | 318.9 | 3 | 2207963 |
| KiLLKiSS | 原附件 | 146.605 | 1842.8 | 3 | 3230947 |
| 可惜没如果 | main自动算法 | 15.133 | 331.3 | 2 | 780130 |
| 可惜没如果 | 原附件 | 162.348 | 879.9 | 1 | 1287455 |
| 小星星 | main自动算法 | 4.064 | 251.1 | 1 | 172394 |
| 小星星 | 原附件 | 38.617 | 784.7 | 1 | 321471 |
| 鲜花 | main自动算法 | 18.030 | 357.5 | 2 | 1639637 |

本地完整证据位于 `/home/kenqia/issue69-context/evidence/`，清单为该目录上级的 `inputs.json`、`inputs-v2.json`、`versions.json`。各目录保留measurement、日志、PDF、全部渲染预览和实际可得中间材料。原附件《鲜花》及优化程序当时尚未完成，后续结果另行追加，不能把本表当最终对照。

根Agent实际查看了main前三条全部6页，以及原附件KiLLKiSS全部3页和可惜没如果1页。可见标题、速度、拍号、开头和结尾，KiLLKiSS可见1至135小节、标准曲结尾至88；暂未发现明显整行丢失或顺序错误。附件白底清理比main残留网格更干净，但这些页面概览不证明逐符号音乐一致。分页数量差异本身不证明缺行，附件的连续行组数量也不是五线谱数量。

主要已测问题是附件KiLLKiSS接近2GB的内存观察值，难以给服务器网页、worker和系统留下余量。静态分析还发现附件有全画布回跳搜索、按色彩剔除、多样本整图堆叠与超高块硬切风险；这些分别需要受控反例和真实材料验证，不能仅凭源码描述就称已经发生。

## 复跑

在项目依赖环境中，以下命令将输入清单中的全部视频交给指定程序。`INPUTS` 与 `VERSIONS` 是本地冻结JSON路径，`NEW_RESULTS` 必须不存在。

```sh
python tools/compare_script_core.py \
  --manifest "$INPUTS" --versions "$VERSIONS" \
  --output "$NEW_RESULTS" --program main --checkout "$FROZEN_MAIN"

python tools/compare_script_core.py \
  --manifest "$INPUTS" --versions "$VERSIONS" \
  --output "$NEW_RESULTS" --program attachment \
  --attachment "$ORIGINAL_SCRIPT" \
  --attachment-sha256 2ea5ddd758665efd48320d15e3be5c39706dd6dc290eb4e6dd738a75b87ee239
```

`--sample xianhua` 可补跑同一固定清单的新增项，不替代其他样本回归。优化程序须在安装后使用同一清单，并保存每次失败及修正版本。程序的成功、Agent实际查看与用户最终质量确认分别记录。
