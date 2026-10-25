# Issue #83 高级参数与显式schema升级实验

本轮实现程序、CLI与网站的时间选段、手动百分比谱区、参数持久化和媒体下载前600秒限制。独立Skill未改。证据根为 `/tmp/drum-issue82-context/83/`；临时证据不随仓库分发。

## 验证环境与命令

使用 `/tmp/drum-issue82-env/bin/python`，Python3.12。运行前将该环境的 `bin` 放在 `PATH` 首位并设置 `PYTHONPATH=src:tests`。没有添加依赖。

公开契约中的四个新增方法分别覆盖非法参数、真实合成视频通过Python/CLI/HTTP及worker、原来源601秒拒绝和600秒继续实测完整性检查、表单默认折叠与数值可编辑。维护新增v3升级验证，保留并迁移v1/v2升级断言。`01`至`06`的red/green日志保存每个slice的先失败、后通过证据。`focused.log`记录六个方法通过，包含v2/v3升级与原期限保持。

首轮完整发现使用：

```sh
PATH=/tmp/drum-issue82-env/bin:$PATH PYTHONPATH=src \
  python -m unittest discover -s tests -v
```

`regression.log`记录227项、169.547秒，2个失败和3个错误。维护失败来自新增结果摘要字段未同步到备份校验，已将 `conversion` 按manifest存在性同步到worker与maintenance，旧摘要保持兼容；旧schema测试快照也显式移除新增列。`07-green.log`记录全部三个维护失败方法修正后通过。

另一个错误来自既有同时取消/SIGTERM测试在任意时刻SIGSTOP worker，可能冻结SQLite事务锁，HTTP合法返回503而测试直接取state。保留原失败日志，并在测试中用外部SQLite排他事务作为停驻边界，确认进程实际停驻后释放边界。生产取消行为未放宽。`signal-fixed.log`记录相同生命周期断言连续三次通过。

修正后未重复本分支全回归；完整最终回归由Issue #86的集成版本执行。`node --check src/drum_score/static/app.js`、`python -m compileall -q src/drum_score tests`及 `git diff --check`通过。

Root另用真实Chromium核验表单默认折叠、手动数值可编辑、无来源播放器、非法时间不发POST、出站参数、390px移动布局及页面无异常。证据见 `/tmp/drum-issue82-context/browser83-report.json`，不把静态HTML断言称为浏览器验收。

## 真实来源选段

沿用Issue #84匿名获取并核验的开发来源BV1fbFczHE1r、p1、CID35825388527。完整来源245.3秒、852×480，SHA256为 `abbb40222ce2c3db0ae9b390f2a9dcd1e492182c292d23ba875e1b437df1cc93`。旧整曲采样在61.5至62秒处首次无法配准，证据见 `/tmp/drum-issue82-context/84/baseline/`。

用新CLI显式选择 `[0,50)`，先保留完整画面，再手动选择 `[0,0,100,92]`百分比，避开画面底部原本只显示一部分的下一行：

```sh
PATH=/tmp/drum-issue82-env/bin:$PATH PYTHONPATH=src python -m drum_score \
  /tmp/drum-issue82-context/84/BV1fbFczHE1r-source/BV1fbFczHE1r-p1.mp4 \
  --output /tmp/drum-issue82-context/83/real-selected-four-rows \
  --end-seconds 50 --region-percent 0 0 100 92
```

两次均发布PDF、全部预览与manifest，保持来源完整hash、原生PTS/time_base及 `reliable=false`，`conversion.is_excerpt=true`。完整画面版本1页，首帧0、尾帧49.967秒、耗时4.932秒。已实际查看其唯一预览，能看到标题、四个完整谱行与原画面底部的部分下一行。第二次手动裁剪的产物和参数单独保留，不覆盖首次产物。

这证明用户能明确选择避开失败时段的区间，不表示整曲配准已修复，也不是逐符号音乐校对。固定覆盖物开关在本票贯通参数，实际检测与补帧算法由Issue #84接入；视频缓存与每次命中前的独立元数据核验由Issue #85接入。未改生产数据库、推送、部署或远端工单状态。
