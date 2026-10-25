# Issue 82 自动谱区审查修复

正式规格审查发现自动选区仍按最大白底连通域选择。合成双面板来源中，较大的空白面板遮蔽较小谱面。公开 `drum_score.convert` 返回 `unsupported_layout`，手动选区完成四行。

## 修复与验证

选区保留完整白底候选，通过七个分散的已有原生帧检查 `system_groups` 五线结构。证据不足时检查其余已采样候选帧；持续证据优先，多个候选均有持续证据时拒绝。仅有一次谱面观察仍可支持唯一候选。唯一纸面候选无结构证据时继续后续验证。已有超过八成白底的全画面路径保持原样。每帧和每个候选检查均接受任务资源、期限及取消检查。

公开转换测试先失败，再修复通过。最终三个公开测试用时 7.038 秒，覆盖大小面板选择、标题/署名与边缘 RGB 逐像素保留、短暂干扰、两谱面歧义拒绝及晚出现单帧证据。晚出现合成序列仍因原配准阶段的空白/谱面切换返回 `discontinuity`，自动与手动选择一致，未将其记为完整转换通过。

转换回归 29 项用时 44.885 秒全部通过，包含原全画面、细黑边、彩色边缘保留、固定覆盖物、重复系统及首尾完整性。独立公开复现脚本修复后自动和手动均完成四行。没有新增生产依赖。

验证命令：

```sh
PATH=/tmp/drum-issue82-env/bin:$PATH PYTHONPATH=src python -m unittest discover -s tests -p test_public_contracts.py -k automatic_region -v
PATH=/tmp/drum-issue82-env/bin:$PATH PYTHONPATH=src python -m unittest discover -s tests -p test_script_conversion.py -v
PATH=/tmp/drum-issue82-env/bin:$PATH PYTHONPATH=src python /tmp/drum-issue82-context/review-region-repro.py
```

红、绿和末轮证据保存在 `/tmp/drum-issue82-context/review-region-*.log`。完整程序回归、最终构建与安装由集成验证另行记录。

## 真实来源限制

此修复的双面板改善由合成来源证明，尚无核验过的真实来源证明同类改善。既有开发来源恢复由其他配准修复证明，不能重新归因于本修复。固定覆盖物的真实来源改善也仍缺证据，不能将合成 Logo 测试记为真实来源验收。未读取或使用保留集调参；所有自动产物仍为 `reliable=false`。
