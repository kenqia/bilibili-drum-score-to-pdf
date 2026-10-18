# README 展示素材

本目录保存仓库头图与 12 秒循环 GIF 的可编辑源文件。它不参与 PDF 生产流程。方向与素材边界见 [制作说明](VIDEO_SPEC.md)，配色和字体见 [视觉规范](frame.md)。

## 素材来源

`assets/xianhua/` 保存 2026-10-18 本次《鲜花》任务的原生首帧、第 7/11/16 小节起原裁剪谱行、三张 PDF 预览和三页 A4 PDF。复制文件逐字节核对，路径、SHA-256、来源审阅和最终三页审阅见[来源清单](assets/xianhua/provenance.json)。视频水印署名「帅气迷人的小磊子」，演唱者回春丹，谱面署名「JIAN磊」。音乐与谱面权利归原权利人。

任务包含 27 条完整谱行，覆盖第 1–113 小节并保留反复结构；四组真实宿主重绘与最终三页已查看。小节号和重叠行核对证明接续，未声明严格逐帧时间覆盖。旧《可惜没如果（新版）》素材与其来源清单仍保留在 `assets/`，当前展示不再引用。

`index.html` 编排单场景流程动画，`hero.html` 是静态头图。动画使用固定版本 GSAP 3.14.2 的 CDN 脚本，遵循其文件头注明的 [GSAP 许可](https://gsap.com/standard-license/)。预览与渲染需要能获取该脚本；工具会编译并加载动画。字体依赖本机 WenQuanYi Zen Hei 与 DejaVu Sans Mono。

## 重新渲染

仅制作展示素材时安装 Node.js 22+、FFmpeg 和本目录的开发依赖。它们不加入项目 Python requirements。

在本目录运行：

```sh
npm install
npm run check
npm run render
```

输出为 `docs/images/workflow.gif`，960×540、12 fps、12 秒循环。源工程按 1280×720、15 fps 渲染，再压缩为 README 展示版。`index.html` 内的 `data-duration` 和 GSAP 时间线共同定义时序。修改后重新查看起始、中间、最终和循环衔接。

如果已有兼容 Chrome，可为命令临时设置 `HYPERFRAMES_BROWSER_PATH` 指向其可执行文件，避免下载另一浏览器。不要把该路径写进宿主配置。

静态流程图提取自本次 1280×720 完整 GIF 的 8.5 秒帧；头图从 `hero.html` 按 1440×560 截图。截图前等待字体和图片加载。README 同时保留静态流程图与真实页面，便于不播放动画时查看。

工具缓存、依赖和中间渲染使用本地目录。只提交源文件、来源清单以及最终展示图片。
