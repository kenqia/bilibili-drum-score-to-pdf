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

- `success`：交付 `score.pdf` 和 `manifest.json`。后者保存标题图、谱行图片、源画面坐标、视频实际时间和 PDF 页码。
- `waiting`：展示 `issues` 中编号、截图、源视频时间和具体问题。保持结果目录供后续继续；未解决的疑点不能称为完成。
- `failed`：说明 `error.message` 和源视频分辨率。无法读取或画质不足时，请用户提供能显示完整谱行的清晰本地视频。

## 匿名链接与本地兜底

输入可为 `https://www.bilibili.com/video/BV…`，分 P 使用 `?p=2`，缺省选择第一 P。只使用匿名公开接口，不登录，不读取 Cookie、认证或密钥。媒体地址只在内存中读取，不显示、不持久保存、不传给 ffmpeg 或 ffprobe；这些工具只读取已经下载的本地视频。

链接命令在 WSL 下用 `timeout 120s uv run ...` 限制整次尝试。若退出码为 124 且尚无 JSON，报告网络超时并转本地输入；不要把残留文件当成转换结果。链接取得视频后执行同一个转换入口。查看 `origin` 的 BV、分 P、CID 和 `api_quality`，同时查看 `source.width` 与 `source.height` 的实际尺寸。元数据或请求的画质不能当作实际高清获取证据。失败或低清时说明原因，请用户提供清晰本地视频，在新的结果目录重跑。不要尝试其他登录接口、换认证或绕过限制。

下载只支持公开单文件 MP4，不跟随重定向。每次阻塞读取设 20 秒 timeout，元数据最多 2 MiB，视频最多 2 GiB，读取循环最多 30 分钟。DNS 等系统操作可能额外等待，不能承诺固定总耗时。任一拒绝或不支持的响应立即停止，不自动重试。接口维护依据见 [references/anonymous-input.md](references/anonymous-input.md)。

## 当前支持范围

当前切片支持白底、固定、多行谱面的本地短视频。入口自动定位白底谱面，从完整五线谱行之间的空白裁剪，保留首帧可提供的标题、速度、拍号和行下标记。逐行排入 A4 纵向页面，分页不拆开谱行。

谱面随时间变化时返回等待状态和证据，不能以单张窗口声称整曲恢复。连续滚动、跳行切换、光标恢复和回答后继续仍由后续切片完成。不要擅自删除光标所在像素或猜补音符。

清晰度检查依据源谱面宽度和五线间距。通过检查只表示满足当前启发式门槛，不代替打印验收。输出后渲染 PDF，对照源画面检查每页的五线、符头、符杆、标题和分页；发现缺失时报告疑点。

## 本地检查

在仓库根目录运行 CLI 验收测试。夹具独立绘制记谱特征，经真实 ffmpeg 视频编码和 PDF 渲染验证。

```sh
uv run --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt python -m unittest discover -s tests -v
```

测试还需要 `pdfinfo` 和 `pdftoppm`。合成固定谱面通过不能替代《七里香》整曲验收。
