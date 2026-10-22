# BBDownNext 2.3.0 有界元数据构建

公开链接解析使用 `metadata-bounded.1`，基于上游 `v2.3.0`，保留 MIT 许可。这是项目构建，不是上游原始发布文件。

| 项目 | 固定值 |
| --- | --- |
| 上游 | https://github.com/KaiHuaDou/BBDownNext/tree/v2.3.0 |
| SDK | .NET SDK 10.0.401，Linux x64 |
| 构建 | NativeAOT，Release，linux-x64 |
| 可执行文件 SHA256 | `d5fe48f6c2bf2e388937d3c8985c1e3dcca678e5a8d8345fa5c31e36793baf0a` |
| 原版 Linux x64 SHA256 | `8e149b6d90a48bd3665b9c7efb5056e443e4a5c6d04313b8c4d21cfc6e70d114` |

生产源码只有两处调整：

- `BBDown.Core/Util/HTTPUtil.cs` 的 `TruncateForLog` 保留最多 2 MiB 字符，避免原 8192 字符截断必要的 view JSON。
- `BBDown.Core/Util/HttpTransfer.cs` 的 `MaxResponseBytes` 从 64 MiB 改为 2 MiB。读取循环检查解压后的累计字节，不依赖 Content-Length。

CLI 仅解析元数据，原始输出总量另受 Python 的 2 MiB 限制。总输出超过预算仍失败，不能把单个响应预算理解为所有响应一定可以同时达到上限。

构建使用独立 SDK、NuGet 缓存与空用户目录，只启用公开 NuGet 源，不导入用户配置或代理。命令如下，在已经应用随附补丁的准确源码目录执行：

```sh
dotnet publish BBDown -r linux-x64 -c Release -o /absolute/path/output --configfile /absolute/path/NuGet.Config
```

SDK 与 NuGet 缓存不是运行时依赖，不安装到服务器。运行时只交付单文件、MIT 许可、准确源码归档、补丁和构建记录。重新构建可能产生不同摘要；未经审阅和验证，不把新摘要加入允许清单。

安装和删除范围见[安装指南](install.md)。回滚时切回旧应用发行和旧 worker unit，不替换全局工具，不修改网络路由。
