# Issue 91 翻页接续实验

实施从整合提交 `8d9cef7459cb7f70e4854ce554688979be3439c4` 开始。测试 seam 使用已确认的公开 `convert`，来源为真实 FFmpeg 编码的合成谱面，不代表真实音乐来源验收。

## 第一切片

`PageTransitions.test_clean_native_page_cut_preserves_both_complete_pages_and_limits` 使用两张完整页的稳定画面和一次硬切。修改前公开转换在 1.750 至 2.000 秒报告 `discontinuity`，RED 耗时 2.339 秒。加入共享补帧预算的局部连续原生窗口后，GREEN 耗时 4.162 秒。

测试核对四行谱面、已知两张原图的完整像素、每个原生帧的 PTS/time_base、同次解码序列与相邻 ordinal，以及连续性待核对提示。PDF 和预览只包含谱面，程序说明保留在结果数据中。该切片尚未完成真实来源、全量反例与公开入口矩阵验收。
