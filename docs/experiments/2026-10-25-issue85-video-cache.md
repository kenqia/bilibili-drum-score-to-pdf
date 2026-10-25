# Issue #85 视频缓存验证

本轮为匿名网站增加独立视频缓存，共享同来源获取，不修改独立Skill。默认缓存额度和硬上限均为1GiB，发布后保留24小时，命中不续期。隔离测试缩小额度或期限，未修改正式服务器、认证或服务配置。

## 环境和边界

使用Python3.12独立环境 `/tmp/drum-issue82-env`，未新增依赖。测试证据保存在 `/tmp/drum-issue82-context/85-*`，这些临时证据不随仓库分发。

```sh
PATH=/tmp/drum-issue82-env/bin:$PATH PYTHONPATH=src:tests \
  python -m unittest test_video_cache -v
PATH=/tmp/drum-issue82-env/bin:$PATH PYTHONPATH=src:tests \
  python -m unittest discover -s tests -v
```

`tests/test_video_cache.py`通过HTTP、真实worker、进程、FFmpeg和实际文件验证。`NETWORK`只替换BBDown匿名元数据和媒体HTTP边界，返回合成视频；没有替换转换、缓存协调或supervisor。`SYNTHETIC_NETWORK_ROOT`中的`input.mp4`是媒体，`version`控制强ETag，`duration`控制完整元数据时长，`mode=wait`及`release`控制媒体获取边界，`fetches`逐行记录完整媒体GET次数。Range版本探测不写入`fetches`，不能把它当作所有HTTP请求计数。分P返回不同CID；BV仍保留在来源身份中。失败注入在各测试内追加外部传输或OS边界行为。

## TDD和进程验证

`85-01`至`85-12`保存逐项red和green日志。弱版本旁路基线本来就通过，不冒称red。新缓存能力的合成失败也不冒称真实历史缺陷复现。

公开worker验证覆盖顺序命中与单次实际下载、并发合并、初始等待者取消、最后等待者等guardian停止、固定期限、过期清理、原来源超过600秒的命中前拒绝、分P及版本隔离、弱版本旁路、优先流故障后的现有格式回退、不同备用资源使用相同ETag时旁路缓存、容量不足与未知文件保留。维护入口验证缓存备份、hash核验和恢复后新身份，原期限不变。旧v1/v2/v3升级测试显式保留相应旧schema，最终v4统一加入高级参数和缓存表。

路径安全测试在命中后、子进程读取前真实unlink并替换为合成symlink，原转换仍通过已持有FD读取原hash，替换目标不被读取或删除。`85-held-unlinked-green.log`另验证原路径unlink后登记媒体仍占缓存额度，其他来源跳过缓存，持有者完成。`85-06`在媒体发布后、ready事务前杀死worker，恢复后不能命中半份发布，已登记视频被清理。

`85-12-short-transfer-red.log`记录旧实现在HTTP声明长度大于实收完整小视频时错误发布`complete/fill`。修正后完整传输除了核对响应ETag和Content-Length，还必须核对累计实收字节与版本长度，结果为`source_changed`且无缓存媒体发布。FFprobe可读容器时长不能替代这一检查。`85-cache-budget-*`验证公开worker拒绝超过1024MiB的缓存额度。

## 真实版本协议观察

对已经授权的两个开发来源进行匿名Range验证，分别为BV1fbFczHE1r的p1、CID35825388527，以及BV1Xp4y157oo的p1、CID1213901195。前者245.3秒、852×480，后者197.322秒、640×368。各自重复请求均返回206、强ETag、相同资源身份摘要和完整字节数；包含一次If-Range复核。最终探测读取6字节，之前一次读取4字节，总计10字节媒体响应体。

安全记录位于 `/tmp/drum-issue82-context/85-validator.json` 和 `85-validator.md`。只保留ETag摘要、资源hostname与path摘要、格式、长度及公开来源身份。签名地址、原始响应、字面ETag和媒体响应体没有持久化。

这证明两个开发来源具备所需版本信号，不能推广为所有B站CDN都支持强验证。运行时每次重新核验完整来源与版本；缺少可信字段则走原任务暂存路径。该观察不证明音乐正确性或实际看图验收。

## 回归状态

配准算法合入前，`85-full-program.log`记录完整程序246项、238.043秒，2项失败。预算拒绝测试错误期待旧worker会输出诊断，已按既有契约改为退出码2且未创建数据根。另一个失败是实际共享获取缺陷：第二等待者看到`filling`登记时被误当成已发布来源失效，产生第二次下载。独立重现保持失败后，修正为`filling`等待者加入共享future，只有已发布`ready`失效且仍持有时独立旁路。`85-coalescing-fix-green.log`记录取消合并、过期持有、unlink持有额度及预算拒绝4项通过，16.375秒。

合入配准算法`dcf092b`后，`85-post-registration-targeted.log`记录18项缓存、公开选段/区域、v3升级和缓存上限21项执行全部通过。该命令另误写一个不存在的时长方法名，loader报错，不能称整条命令成功；正确方法单独运行并保留`85-post-registration-duration.log`。编译、静态JavaScript语法和`git diff --check`通过。

独立Skill没有修改，不在本票运行Skill测试。真实重复提交和最终集成安装、八路组合及完整回归由后续集成验收补充，不把已失败的首轮完整发现报告为通过。
