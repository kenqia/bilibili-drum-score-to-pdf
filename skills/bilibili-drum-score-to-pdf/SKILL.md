---
name: bilibili-drum-score-to-pdf
description: 将 B站链接或本地视频中已有的白底多行鼓谱整理成 A4 PDF，交付源视频时间和疑点截图。
---

# 鼓谱视频转 PDF

使用本文件旁的 `scripts/convert.py` 作为统一入口。先交付文件包，不自行安装到用户的技能目录，也不修改 Codex 配置。

## 运行

需要 `ffmpeg`、`ffprobe`、`uv` 和 Python 3.12 或更高版本。入口使用 PEP 723 声明依赖，`uv` 在独立环境运行，不修改全局 Python 包。

```sh
uv run /absolute/path/to/bilibili-drum-score-to-pdf/scripts/convert.py /absolute/path/to/video.mp4 --output /absolute/path/to/result
```

选择单独的结果目录。视频和图片在本地处理。Pillow 读取和保存谱行，NumPy 与 OpenCV 检查白底区域和五线布局，ReportLab 排版 PDF。没有识别 API，也不听音生成乐谱。

入口向 stdout 输出 JSON，stderr 提供进度。先检查 `status`，再向用户交付结果。

- `success`：交付 `score.pdf` 和 `manifest.json`，同时检查 `complete`。若为 false，说明用户已明确接受的缺失位置及 `limitations`，不能称为完整还原。`manifest.json` 保存标题图、谱行图片、源画面坐标、视频实际时间和 PDF 页码。
- `waiting`：展示 `issues` 中编号、截图、源视频时间和具体问题。展示对应证据后等用户在聊天中明确回答；保留结果目录，按下文继续。未解决的疑点不能称为完成。
- `failed`：说明 `error.message` 和源视频分辨率。无法读取或画质不足时，请用户提供能显示完整谱行的清晰本地视频。

## 匿名链接与本地兜底

输入可为 `https://www.bilibili.com/video/BV…`，分 P 使用 `?p=2`，缺省选择第一 P。只使用匿名公开接口，不登录，不读取 Cookie、认证或密钥。媒体地址只在内存中读取，不显示、不持久保存、不传给 ffmpeg 或 ffprobe；这些工具只读取已经下载的本地视频。

链接命令在 WSL 下用 `timeout 120s uv run ...` 限制整次尝试。若退出码为 124 且尚无 JSON，报告网络超时并转本地输入；不要把残留文件当成转换结果。链接取得视频后执行同一个转换入口。查看 `origin` 的 BV、分 P、CID 和 `api_quality`，同时查看 `source.width` 与 `source.height` 的实际尺寸。元数据或请求的画质不能当作实际高清获取证据。失败或低清时说明原因，请用户提供清晰本地视频，在新的结果目录重跑。不要尝试其他登录接口、换认证或绕过限制。

下载只支持公开单文件 MP4，不跟随重定向。每次阻塞读取设 20 秒 timeout，元数据最多 2 MiB，视频最多 2 GiB，读取循环最多 30 分钟。DNS 等系统操作可能额外等待，不能承诺固定总耗时。任一拒绝或不支持的响应立即停止，不自动重试。接口维护依据见 [references/anonymous-input.md](references/anonymous-input.md)。

## 当前支持范围

几乎完全均匀的纯色卡片，以及清晰、均匀背景的文字标题卡和结束卡，可作为无谱面边缘忽略。检查文字清晰度及前景形状，任一长水平线都阻止忽略，局部五线和残行继续进入疑点。纯色卡片要求各 RGB 通道全图极差不超过 2 级；渐变、模糊或无法分类的边缘仍需确认，中段卡片不会被忽略。`ignored_edges` 保存忽略边缘的时间范围、原图与分类规则；`boundaries.end` 保留实际最后一帧，另可从忽略记录核查结束卡。全片没有完整谱行不得成功。此规则只识别均匀纯色卡和清晰文字卡，不能证明任意图片封面没有隐藏谱面。

当前入口支持白底、多行、固定或向上推进的本地视频。入口自动定位白底谱面，从完整五线谱行之间的空白裁剪，保留首帧可提供的标题、速度、拍号和行下标记。逐行排入 A4 纵向页面，分页不拆开谱行。

接续只比较相邻窗口的有序重叠与向上位移。停留画面去重，后续再次出现的相同谱段保留；不进行全局图片去重。连续滚动累积位移，边缘残行待完整出现后才保留。查看 `seams` 的前后截图、时间及匹配谱行，逐个核查；同时检查 `boundaries` 的开头与真实末帧。

小点、细符杆和原蓝色记号也参与内容比较，包括五线上的记号；不能因其占整行比例小就忽略变化。暂时模糊时先检查后续实际画面。只有短暂轻度模糊、位置不变、两端清晰内容一致，且中间每个采样原图都满足局部像素检查时才恢复；强模糊仍等待，打印只选真实清晰帧。查看 `recoveries` 的两端及中间原图和时间。该检查是有限范围的启发式，无法证明采样之间或低于像素残差门槛的变化。不同谱面、无法确认的模糊段及缺少双端证据的开头/结尾仍需明确回答；`unreadable_observations` 保留原图，等待结果的 `readable_followup` 提供已检查的后续清晰画面。

无唯一重叠、顺序不明或首尾残行未恢复时返回等待。`candidate_rows` 是未确认候选，不能当成完成曲谱。`continuation` 明确要求恢复时重放原视频，不能仅将已保存前缀排版后声称整曲完整。入口跟踪同一谱行的真实候选，优先选择整行无浅蓝竖块遮挡的画面，再按清晰度选择。`observations` 保存观察时间和质量，`original_image` 保留所选原图，`image` 为只转灰度的打印图。原谱蓝色休止横线和数字保留为灰度墨迹，不按颜色删除。

没有干净整行候选，或遮挡期间缺少同位置互补观察时，返回 `cursor_occlusion`，展示原图、源时间及后续清晰证据。光标移动后的可见内容须互补覆盖隐藏区域，并与真实干净整行一致；前后干净帧相同不能证明中间不透明遮挡没有改变。不能靠擦除、补画或放大宣布恢复。`quality` 报告源分辨率、实际谱行宽度/五线间距/打印有效 DPI、工具版本和未恢复行；这些门槛不能代替逐页视觉验收。

清晰度检查依据源谱面宽度和五线间距，并按 A4 实际可打印宽度计算每条谱行的 effective DPI。低于 150 DPI 返回 `failed`/`low_print_resolution`，不会生成声称合格的 PDF；150 至不足 200 DPI 仅是最低可打印候选，200 DPI 以上也仍需锐度和逐页视觉验收。不会通过插值放大或默默缩小谱面过门槛。输出后渲染 PDF，对照源画面检查每页的五线、符头、符杆、标题和分页；发现缺失时报告疑点。

## 本地检查

完整仓库包含 CLI 验收测试；单独 skill 文件包用上面的绝对脚本路径转换。随仓库交付时，在仓库根目录运行测试。夹具独立绘制记谱特征，经真实 ffmpeg 视频编码和 PDF 渲染验证。

```sh
uv run --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt python -m unittest discover -s tests -v
```

测试还需要 `pdfinfo` 和 `pdftoppm`。合成固定和滚动谱面通过不能替代《七里香》整曲验收。

## 聊天回答与恢复

用户只需在当前聊天中回答，不要求用户填写 JSON。展示疑点编号、源视频时间、截图、相邻参考和具体问题。Codex 仅根据用户明确表达的选择，把回答映射到 `issues[].choices`，写入本地答案文件，再运行：

```sh
uv run /absolute/path/to/bilibili-drum-score-to-pdf/scripts/convert.py --resume /absolute/path/to/result --answers /absolute/path/to/answers.json
```

没有新回答时仅使用 `--resume`，确认结果仍在等待。不能因等待时间、含糊回复或重试而默认确认。`answer_error` 表示回答无法应用，原进度和此前确认保留。`invalid_progress` 表示原视频、证据或状态已变更，应报告失败并保留目录，不覆盖旧结果。

需要把聊天回答写入答案文件时，读取 [references/resume.md](references/resume.md) 的动作含义、补图要求和恢复约定。只使用当前疑点提供的选择；单张补图不能自行证明重复段落或窗口顺序。

恢复前校验原视频、交付 PDF 和全部引用证据的指纹，以及 manifest 与 state 的一致性。PDF 丢失或被替换、混代结果及旧版缺少 PDF 指纹的状态都返回 invalid_progress 并保留目录，核查后应在新的空目录重建。收到有效回答后重放原视频到末尾或下一个疑点，不能直接把此前保存的前缀排成完整 PDF。此前答案、来源和旧证据保留。对同一个答案重复恢复不会插入重复谱行。新转换只接受空结果目录，已有目录使用 `--resume`。
