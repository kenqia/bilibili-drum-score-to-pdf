# 豆包匿名获取诊断

2026-10-19。基线提交 `21f9feae4e0c2c8ec76713a66a66539e9d2a7a99`，与用户报告的豆包安装提交一致。实施工作区为 `/home/kenqia/my_folder/bilibili-drum-score-doubao`，分支 `codex/doubao-anonymous-acquisition`。原工作区的修改和实验保留。

## 观察与限制

原提交在 Codex 本地通过公开 `prepare` 获取鲜花 `BV1Yw4m1Y7YH`，实测 H.264、1920×1080、25fps，匿名获取且无需备用媒体地址。证据位于工作区 `work/doubao-acquisition/baseline.json` 与 `baseline/record.json`。这只证明本地来源准备成功，没有新的 PDF 或逐页审阅。

用户转交的豆包结果显示：原 Skill 在网页阶段失败，错误类型为 `OSError`，来源 HTTP 状态为空。豆包自行补写的探针报告环境代理 CONNECT 403；禁用代理时网页 HTTP412，view API HTTP200。该脚本与原探针不同，直连替代了沿用代理的标准库比较。未取得原补写脚本，不能视为控制变量实验，也不能证明 API200 已能下载媒体。

这些结果优先指向豆包执行环境与本地的网络路径差异，尚不能归因于手机 VPN。三种请求比较见工作区 `work/doubao-acquisition/发给豆包-短诊断2.txt`，需在豆包实测。

## 已复现的协议问题

生产连接先调用标准库 `set_tunnel`，再把 `_tunnel_host` 替换为验证过的公共 IP。Python 3.12+ 在 `set_tunnel` 中生成域名 `Host`，导致 CONNECT 目标为 IP，Host 仍为域名。[Python 3.12 文档](https://docs.python.org/3.12/library/http.client.html#http.client.HTTPConnection.set_tunnel)要求 Host 匹配 CONNECT 目标，并说明 3.12 起使用 HTTP/1.1 且自动生成 Host。

在现有 CLI 代理测试的实际报文处添加目标与 Host 一致性断言后，原实现失败，返回 acquisition failure。日志 `work/doubao-acquisition/connect-before.log`。修复仅在每次隧道连接时将 Host 同步为公共 IP 及端口，IPv6 使用方括号，并在 finally 恢复原参数。公共 IP 固定、TLS 原域名验证、代理使用方式与认证隔离保持原规则。

该缺陷已在本地证明；它是否造成豆包此次403仍待三路比较，不能将两者等同。

## 验证

修复后，已有链接测试21项通过，9.386秒，日志 `work/doubao-acquisition/link-after.log`。另增一个含3种地址排列的测试，验证IPv4、IPv6、首个地址拒绝后的重试、请求Host、参数恢复、TLS域名和代理专用合成认证头的保留。该项单跑通过。

短探针在本地已安装Skill上完成3次API请求，均HTTP200、API code=0且BV匹配，证据 `work/doubao-acquisition/local-connect-probe.jsonl`。用合成异常分别验证HTTP412与CONNECT403，只输出各自状态，不暴露合成敏感标记。探针仅在临时进程修改方法，退出撤销；没有修改已安装Skill。

完整带Mido回归195项、364.245秒，全部通过、无跳过，日志 `work/doubao-acquisition/full-after.log`。命令为 `uv run --quiet --isolated --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt --with mido==1.3.3 python -m unittest discover -s tests -v`。Python3.12.12单独执行新增连接测试亦通过。当前状态记录于本工作区 `work/engineering/CURRENT.md`。源码编译、references同步检查与diff空白检查通过。当前无豆包下载修复成功、整曲制谱或远端发布的证据。

## 豆包实际下载与通用恢复

用户回传的双路短探针中，原方式与匹配Host后的请求均为proxy CONNECT403，说明单独的Host修复未解决此宿主拒绝。随后临时直连API脚本在豆包实际下载鲜花成功，1920×1080、25fps、13725883字节。用户报告文件hash与本地原来源一致，并将文件保存在豆包项目独立来源目录。该结果来自用户转交的实际执行回执，不等于本地新生产版本已安装到豆包。豆包尚未回传新的完整PDF或全部页面审阅。

生产实现默认保持原获取路径；仅代理CONNECT403或视频网页HTTP412触发一次公开API直连恢复，复用原工作进程、1800秒默认总期限、2GiB限制与独占发布。直连只作用于本次opener，不修改环境或代理配置。API核对BV与唯一分P/CID，拒绝互动、跳转和明确受限视频；API分P时长与播放时长容差1秒，文件实测与播放时长容差0.5秒，试看或不完整文件不发布。恢复路线与原触发诊断进入origin；恢复失败保留两段脱敏诊断。不增加依赖、CLI操作、Cookie读取或宿主配置。

在新的CLI获取测试中，先用本地受控代理实际返回CONNECT403，再通过真实互联网API和CDN完成下载。两个新任务分别为鲜花BV1Yw4m1Y7YH，335.32秒、13725883字节、1080p25fps，以及BV1yGGN6XE1B，209.900063秒、7710135字节、1080p30fps。前者SHA256为9f948b7c4eca5c4e981baa2ca37563108393b37b1323b7008eafa8468b19947d，与原正常获取和豆包回执一致。后者SHA256为852a8e382374b0f8b1112efd13951020dba136cbd4f778389d5e42e3da62f463。证据 `work/doubao-acquisition/live-recovery-retry.jsonl` 及其独立任务/来源目录。

首次受控代理真实尝试在初始DNS处失败，尚未触发CONNECT，记录于 `live-recovery.jsonl`。随后独立DNS检查两域均解析成功，同实现重新运行上述两曲通过。保留首次失败，不据此添加DNS例外或扩大恢复触发条件。

针对性验证：API恢复7项4.292秒，链接22项9.220秒，真实进程/信号期限6项10.263秒，均通过。新获取矩阵涵盖CLI、工作流prepare、acquire，另验证错误/歧义分P、试看/受限响应、私有媒体DNS、文件实际时长、proxy407与来源HTTP403不触发恢复，以及恢复过程不能重置总期限。日志 `api-security.log`、`link-final.log`、`lifecycle-final.log`。本轮完整带Mido回归202项、353.780秒，无失败或跳过，日志 `work/doubao-acquisition/full-api-final.log`。包内协议链接检查在最后文案缩短后单独通过。

下载成功不等于鼓谱完整。等待用户通过豆包原任务使用已保留来源继续正常stage和实际全部PDF页审阅；本次未调用宿主生图，也未更改导航、裁剪或排版规则。
