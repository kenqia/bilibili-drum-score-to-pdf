# Issue #72 匿名网站实施记录

2026-10-21。从集成提交 `7a8c1af5e24031f2f9824527f589240c58dcb7f3` 创建独立分支 `codex/issue-72-website`。开始实施前，主任务已明确放行 #71 gate。保护原工作目录、已有实验、桌面结果和其他worktree。没有远端写入或公开部署，未改动用户认证或全局配置。

## 实施范围

新增 FastAPI HTTP适配、SQLite持久队列、独立串行worker和中文同源页面。10个等待加1个活动任务、每IP一个未完成任务由事务和唯一索引约束。所有任务操作使用独立256位能力凭据，数据库只存摘要；默认不信转发头，真实Uvicorn入口显式关闭代理重写和访问日志。JSON解析前限制8 KiB与10秒总接收期限。

复用 `drum_score.convert` 及其真实转换进程，不增加网页转换算法或测试模式。worker锁传给guardian，异常清理仍在进行时不能领取下个任务。核心排他发布的私有attempt目录经过完整性校验后，以持久 `finishing` 决定完成/取消顺序。恢复沿用原完成/到期时间，不移动第二份结果目录。完成后24小时拒绝新读取，响应持有已打开FD，断连和正常结束均关闭。

可选依赖固定 FastAPI 0.156.8、Uvicorn 0.54.0；HTTPX 0.28.1仅用于测试。依赖装在独立虚拟环境，`pip check` 通过。Linux CI增加网站测试依赖，保留既有CLI安装范围。运行说明见[网站指南](../script-product/website.md)。

## 红绿验证

约定测试边界为公开Python、CLI、HTTP/ASGI生命周期和实际OS进程/信号。测试使用真实SQLite、FFmpeg与PDF，替换外部匿名网络边界；故障测试只在SQLite提交和系统时钟边界注入，不mock内部转换或任务状态。

- 首个真实worker测试因尚无worker入口退出1，接入后通过HTTP应用重启、转换、PDF及全部预览读取。
- 首个响应头发出时模拟断连，原实现遗留1个PDF FD。ASGI请求级资源所有权修复后，`/proc/self/fd`无该文件残留。
- SQLite已提交finishing后模拟提交回执丢失，原实现退出0并走失败清理。修复后退出2、保留持久决定，重启恢复complete和原到期时间。
- 两个分块各推进6秒的受控时钟反例，原逐块10秒等待累计12秒仍返回201。单一monotonic截止修复后返回408；没有真实等待10秒或改变事件循环时钟。

真实进程测试覆盖运行取消与显式重试、SIGTERM、HTTP取消与SIGTERM同时到达、SIGKILL、冻结guardian后的锁寿命、并发worker拒绝、10+1队列、重启保留queued及中断任务不自动重跑。完成决定先提交后，重复取消不删除结果；实际杀死worker后仍可恢复。

HTTP验证还覆盖随机能力链接、五类操作越权与不存在任务统一404、过期410、16并发提交配额、同IP与伪造代理头、显式可信代理、完整代理链格式、分块请求大小、外部路径和符号链接拒绝。已合法打开的PDF在unlink后继续读完，新过期请求被拒绝。Python、CLI和HTTP共同矩阵校验公开BV/分P、实际来源hash、全部页面hash、完整发布及未经音乐校对声明，并共同拒绝非公开目标。

## 运行结果与证据

完整回归237项、185.986秒通过，2项Windows专属测试在WSL跳过。其后新增总接收期限、严格代理链和非公开来源矩阵，以及favicon204修正；最终网站与远端共同矩阵22项、22.696秒全部通过，其中HTTP7项包含受控总期限反例。生产模块Ruff E701/E702/F821/F401、compileall、Skill协议同步和diff检查通过。本次没有新增静态类型检查配置。

本机日志保存在 `/home/kenqia/issue69-context/`：

- `website72-full.log`：完整回归。
- `website72-targeted.log`：首轮27项定向验证。
- `website72-targeted-final.log`：最终22项网站与共同矩阵。
- `website72-body-deadline.log`：总接收期限修复后的HTTP7项。

仓库外安装证据在 `website72-packaging-final/`。构建从明确源文件复制到全新目录，不复用仓库build目录；wheel内18个源码和静态资源与工作树逐字节相同，独立安装后再次逐字节核对。`identity.json`、`installed-identity.json`、`smoke-report.json`、`build.log`、`install.log`、`reinstall.log`和`smoke.log`保存结果。

仓库外新虚拟环境的CLI、HTTP和worker三入口可用，`pip check`通过。真实核心处理外部网络替身提供的合成视频，PDF与独立CLI hash一致、全部预览可读、source保持、无staging残留。合成PDF SHA-256为 `aaae4708a0477ddef9ed6e5c5c15d3c0014559e82ebe649e5e84dbd1e5b514e3`，转换包源码SHA-256为 `b1def8581a9efd8b4b6bc869bb810f94140fe3a53ff810931f21d30061c5f788`。

主任务另行保留未提交草稿版本的桌面、手机和真实小星星网页早验收，见外部上下文 `evidence/website-real-draft/browser-report.json`。该记录不替代提交后安装包的独立最终验收。本实现子任务未新增真实网络来源或音乐视觉判断，不将合成完成或页面可读当作谱面质量证明。

## 剩余边界

#73继续完成定时物理清理、容量与磁盘准入、执行中留存空间、失败诊断保留期、中间样本和长图收口，以及schema版本/回滚协议。当前仅访问到期，磁盘文件不会自动清理。慢下载、手机大Blob与正式代理配置仍需后续实际验收。资源采样不等于cgroup硬限制，本机结果不证明2 GB服务器已经通过。没有公开部署或关闭工单。
