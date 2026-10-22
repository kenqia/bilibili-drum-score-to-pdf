# FlClash 出口与服务器隔离获取测试

2026-10-22，用户允许评估魔戒 VPN 和隔离获取，明确要求不修改生产环境、全局网络路由，不读取账号、订阅密钥、Cookie 或 token。用户提供截图确认本机端口7890，并说明腾讯云服务器应该尚未配置魔戒。

本轮已证实服务器测试进程可借用电脑 FlClash，且中立目标观测到公网出口变化。一次有界 B站获取仍返回412，没有下载到视频。尚未确认 FlClash 对 B站的分流策略，不能据此断言该 B站请求已使用魔戒节点，或所有魔戒节点都无法解决412。

## 系统与接入能力

只读核查服务器为 Linux x86_64，已有 mihomo v1.19.21；本机 FlClashCore PID22484 监听127.0.0.1:7890，WSL能连接该端口。没有读取现有 mihomo 配置、FlClash 配置、订阅或认证。

FlClash基于ClashMeta，mihomo提供HTTP和Mixed入站端口。显式代理可以只配置给指定进程，无需启用TUN或自动路由。官方依据见 [FlClash 项目](https://github.com/chen08209/FlClash)、[mihomo 代理端口](https://wiki.metacubex.one/config/inbound/port/)和[TUN设置](https://wiki.metacubex.one/config/inbound/tun/)。这说明接入机制可行，不证明用户套餐的所有节点、协议和服务商限制均已核验。

本次没有在服务器安装新的VPN客户端，而是利用 [OpenSSH 远程端口转发](https://man.openbsd.org/ssh#R) 建立临时路径。

```text
服务器独立测试进程
  → 127.0.0.1:17890
  → 临时SSH连接
  → 电脑127.0.0.1:7890 FlClash
  → FlClash当前规则所选择的出口
```

每次转发先确认17890未被占用，建立后实际核验仅监听127.0.0.1，退出时关闭本次SSH子进程并再次核验端口消失。没有开放新公网端口、修改SSH服务配置或复用服务器原有7890代理。

该路径依赖电脑和FlClash在线，适合本轮验证；它不是服务器脱离电脑独立连接魔戒的验收。

## 公网出口结果

同一中立检测服务的实测结果如下。

| 目标 | 服务器直连 | 通过临时FlClash代理 |
| --- | --- | --- |
| `https://checkip.amazonaws.com/` | HTTP200，118.25.26.140 | HTTP200，66.90.99.58 |
| `https://api.ipify.org?format=json` | 连接拒绝，未取得出口 | HTTP200，66.90.99.58 |

AWS目标同时取得直连和代理结果，足以证明该目标的公网出口发生变化。两个代理目标返回相同IP。此时尚未请求B站；只有该前置验证成功后才进入下载阶段。

## 有界获取结果

下载前再次通过代理检查中立出口，仍为66.90.99.58。随后只提交一次小星星 `BV1np421S78S?p=1` 获取任务。

测试使用独立 transient systemd unit，DynamicUser、PrivateTmp、ProtectSystem=strict、ProtectHome和NoNewPrivileges生效配置，内存上限384MiB、CPU配额50%、无swap、32任务、unit总上限210秒。获取自身上限180秒、64MiB，产物仅进入私有临时目录，不接触生产数据根。

已安装程序的原公共API回退会强制直连。为避免隔离测试绕出代理，仅在临时Python进程中适配传输层，让该回退也经过17890。Python网络审计钩子拒绝该进程及fork子进程连接其他TCP目标；DNS仍使用原系统解析，没有更改DNS或路由。生产源码和配置没有变更。

10.352秒后获取失败，错误为 `http_unavailable`、HTTP412。观测到3次HTTPS请求及3次连入临时代理的TCP连接，其中1次为中立出口检查、2次为B站网页和API回退，两个B站响应均412。直接TCP连接阻止计数为0，回退强制走代理计数为1。原诊断字段 `acquisition_route=public_api_direct` 是未改动程序的路线名称，本轮实际传输仍经过测试代理。

没有完成的视频文件，因此没有媒体hash、完整时长或解码成功结果。临时unit已自动回收，状态not-found/inactive、MainPID0，隧道关闭且17890监听消失。

## 生产保护核验

测试前后全路由表和策略规则的规范化SHA256均一致。

| 项目 | 前后相同的SHA256 |
| --- | --- |
| 路由表 | `e7e27d947a7a81276ae01a5f3719a11c631e38c3a4fbb67f73b570fc4b7acf91` |
| 策略规则 | `c88a415e55c2b1d6ac4dd37c5ec360cbf3f5880a44aa1ecf71598f1d3ce4cbe2` |

nginx、zju-search、服务器原mihomo的PID及运行状态不变；两个生产鼓谱服务仍停止并禁用自启。新SSH连接正常完成，既有SSH服务未改配置。公网鼓谱入口仍HTTPS503，正常CA校验通过。现有代理监听和全局网络没有调整。

## 未决项与后续边界

中立目标走66.90.99.58，不等于B站也走该出口。FlClash可能将国内目标分流为DIRECT。本轮没有读取分流规则或私密连接日志，已请用户只确认当前模式及B站连接的策略是DIRECT还是魔戒节点。这个信息到达前不继续请求或切换节点。

若需后续服务器独立长期使用魔戒，应由用户自行在专用客户端中配置敏感订阅；先确认协议和服务商条件。独立客户端只提供回环HTTP/Mixed端口，不启用TUN、自动路由或系统代理。只给获取进程指定代理，并明确处理当前强制直连回退。生产配置修改和长期部署继续遵循用户授权，不将本轮实验视为已授权上线。

本次脱敏证据位于 `/home/kenqia/issue69-context/vpn-feasibility-20261022/`，包括 `server-preflight.json`、`local-listener.json`、`egress.json`、`download.json`、`server-after.json` 和 `invariance.json`。脚本通过stdin执行，不传输订阅或节点密钥。文档记录和实验脚本不改变应用wheel身份；已部署应用仍为ee9a320版本。
