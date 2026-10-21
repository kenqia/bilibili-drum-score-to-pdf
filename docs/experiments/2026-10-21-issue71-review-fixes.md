# #71 审阅修复验证

2026-10-21，基于集成提交 `fcef1cfeaf611207df0366c10288615826a10cf1`，在独立工作区修复两项审阅发现。仅使用合成输入，没有获取真实凭证、运行四曲真实来源或执行远端写入。

## 重复音乐与原谱位置

公开 `drum_score.convert` 回归使用七行相同音乐，每行带有不同的小节号。原图为 640×1420，视频以 30fps、每帧12像素连续向上滚动；每次0.5秒采样前进180像素，保留340像素真实重叠。

修复前，新增测试实际失败，输出只有三行。原零位移捷径在全局代价不超过0.005时跳过向前搜索，小节号差异不足以阻止捷径。修复后仅在相邻原始RGB观察逐像素相等时直接判定停驻，其他情况比较向前候选。测试确认七行全部保留，累计位移为 `[0, 180, 360, 540, 720, 900]`，长图与已知原图逐像素一致，末页覆盖到1420像素。

重复音乐慢滚、完整首尾和静态来源共四项针对性检查通过，耗时5.818秒。该合成回归证明已知几何及位置保留，不代表真实音乐校对或真实来源质量验收。

## 文件系统错误边界

共同约束矩阵覆盖 Python `convert` 和 CLI。使用合法合成视频文件作为输出父路径，修复前 Python 实际抛出 `FileExistsError`，CLI 退出码为1，traceback包含合成本地绝对路径。

修复将目录准备、临时目录分配及清理纳入公开错误边界。上述输入现在返回 `conversion_failed`，CLI 输出失败JSON并以2退出，不输出私有路径。额外文件系统边界注入覆盖临时分配失败、已有 `invalid_input` 时清理再失败，以及完整发布后清理失败。已有具体错误及完整成功回执分别保留；现有输出、来源与不覆盖检查继续通过。清理故障夹具先实际删除目录，再抛出带合成私有标记的错误，不表示真实不可写介质一定能清理成功。

## 新鲜验证

```sh
PYTHONPATH=src:skills/bilibili-drum-score-to-pdf/scripts:tests \
uv run --quiet --no-project --python 3.12 --isolated \
  --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt \
  python -m unittest test_script_conversion test_public_contracts.ScriptPublicContracts -v
```

23项，18.306秒，全部通过。日志保存于本机 `/home/kenqia/issue69-context/review71-fixes-targeted.log`。包含资源预算、取消、调用方被杀后的子进程与临时目录清理、输出不覆盖、翻页拒绝、完整行组分页和来源记录检查。

本轮未运行完整仓库回归、最终版本四曲资源复测、Windows原生验收或目标服务器验收；由集成阶段继续执行对应验证。
