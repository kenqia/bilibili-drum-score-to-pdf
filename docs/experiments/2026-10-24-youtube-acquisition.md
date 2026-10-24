# YouTube 匿名获取试验

本文按阶段保留失败与后续进展。前两轮未接入；第三轮已下载成功并完成本地接入，详见末节。正式网站未部署本轮代码。

2026-10-24，WSL Ubuntu 本地直连试验未通过。yt-dlp 在 90 秒总期限后停止，没有生成视频文件。程序、CLI 和网站尚未接入 YouTube，网页不能声明已经支持。

## 已确认的实施范围

用户确认先实测匿名下载，成功后再接入产品、补测试和文档；失败则记录证据并报告原因。

- 只修改程序、CLI 和网站，独立 Skill 保持原样。
- 保留 GitHub 仓库及 Python distribution 名称。接入后将网页展示名称改为“视频鼓谱转 PDF”，说明支持 B站和 YouTube。
- B站保留 BBDownNext 2.3.0；YouTube 单独试用 yt-dlp。
- 首版只接受匿名可获取的单条公开视频，排除直播、播放列表批量任务及需要登录或年龄验证的视频。
- 接受 `youtube.com/watch`、`youtu.be` 和 Shorts 单视频链接。附带播放列表参数仍只取当前视频；时间戳不限制转换范围，转换整条视频。
- 只授权本地实施和当前分支提交，没有授权推送、部署或修改服务器网络。

## 独立环境与来源

源码基线为 `9d70e83ac81083bc97504fd68cd777ca542af8d5`，分支为 `codex/parallel-conversions`。试验目录为 `/tmp/drum-score-youtube-dntge58x`，由 `mktemp -d` 创建；依赖没有加入生产安装文件，也没有修改全局环境或认证配置。该目录是临时证据，可能随系统清理失效，本页保留持久摘要。

| 项目 | 实测值 |
| --- | --- |
| Python | 3.12.12 |
| yt-dlp | 2026.10.21 |
| yt-dlp-ejs | 0.8.0 |
| Deno | 2.9.8，Linux x86_64 |
| Deno 可执行文件 SHA256 | `368bca08999e02c6911b8f248167b582276b1f547db5712b6e736d7eda1dbda7` |

通过 `uv venv --python 3.12` 创建环境，再安装 `yt-dlp[default]==2026.10.21`。npm 安装 `deno@2.9.8` 返回 ETARGET，随后从 [Deno v2.9.8 官方发行](https://github.com/denoland/deno/releases/tag/v2.9.8)下载 `deno-x86_64-unknown-linux-gnu.zip` 并解压到试验目录。摘要记录实测文件身份，没有声称已与独立签名或上游校验清单比对。

[yt-dlp 官方依赖说明](https://github.com/yt-dlp/yt-dlp#dependencies)指出完整 YouTube 支持需要 yt-dlp-ejs 与受支持的 JavaScript 运行时，推荐 Deno。本轮没有只安装解析器后把缺失运行时当作网站限制。

## 下载方法与结果

测试来源为 `https://www.youtube.com/watch?v=jNQXAC9IVRw`。这是用于检验基础获取的公开视频，不是鼓谱来源，不构成谱面或音乐验收。

临时 `trial.py` 以显式环境启动子进程，只提供试验环境的 PATH、空白 HOME/XDG_CONFIG_HOME 和 `LANG=C.UTF-8`，不继承代理、认证及用户配置变量。核心参数如下，`TRIAL` 代表新的独立试验目录：

```sh
"$TRIAL/venv/bin/yt-dlp" \
  --ignore-config --no-config-locations --no-plugin-dirs \
  --no-cache-dir --no-playlist --no-progress --no-warnings \
  --no-remote-components --js-runtimes "deno:$TRIAL/deno" \
  --socket-timeout 10 --retries 0 --extractor-retries 0 \
  --max-filesize 32M \
  -f 'best[height<=360]/bestvideo[height<=360]' \
  -o "$TRIAL/probe.%(ext)s" \
  'https://www.youtube.com/watch?v=jNQXAC9IVRw'
```

实际命令由 Python `subprocess.run(..., capture_output=True, timeout=90)` 执行，超时终止该子进程。原始 stdout/stderr 只进入内存，没有保存或输出可能含签名 URL 的原始响应。上述 shell 参数需要配合相同的干净环境和外层期限，不能单独当作生产获取入口。

`result.json` 的持久摘要：

```json
{
  "versions": {
    "yt_dlp": "2026.10.21",
    "deno": "deno 2.9.8 (stable, release, x86_64-unknown-linux-gnu)",
    "ejs": "0.8.0"
  },
  "elapsed_seconds": 90.014,
  "failure_categories": ["overall_timeout"],
  "files": []
}
```

独立网络探针使用 `socket.create_connection((host, 443), timeout=10)` 和系统默认 TLS 校验，不加载 HTTP 代理配置。同轮结果：

| 主机 | 结果 | 耗时 |
| --- | --- | --- |
| `www.youtube.com` | `ConnectionResetError` | 0.075 秒 |
| `github.com` | TLS 成功 | 0.763 秒 |

探针证明本环境当次 YouTube 直连失败，不能证明具体拦截方，也不能推断换到服务器或其他网络后的结果。下载试验只记录外层超时，没有把探针结果冒充 yt-dlp 的内部错误码。没有获取视频，因此未运行 FFprobe、鼓谱转换、PDF 全页验收或真实音乐看图。

## 接入前的后续工作

在可以匿名直连 YouTube 的测试环境复现下载，再进入产品接入。当前没有新增代理、Cookie 或服务器改动授权，不尝试用这些方式绕过本轮失败。

接入时保留旧 B站来源结构，新增独立 YouTube 来源和后端分流。维护恢复会按规范化 URL 核验来源，必须覆盖旧备份兼容。沿用公共 DNS、固定 IP、TLS、目标域限制、总期限、大小上限、完整时长、实际分辨率和解码检查；不能直接把 yt-dlp 默认网络开放给匿名网站。

成功下载只是第一步。还需在 `tests/test_public_contracts.py` 覆盖 Python、CLI 和 HTTP 入口，验证 URL 规范化、单视频语义、来源记录及错误脱敏，完成网站文案与部署依赖说明，再运行针对性验证、程序全回归和真实来源验收。只有这些完成后才更新网页支持声明。

## 本轮验证与审阅

程序全回归使用项目现有独立环境：

```sh
PATH="$PWD/work/engineering/2026-10-23-parallel/venv312/bin:$PATH" \
  python -m unittest discover -s tests -v
```

212 项通过，耗时 154.534 秒，无跳过。日志保存在临时试验目录的 `regression.log`。这些测试验证当前 B站产品回归，不是 YouTube 接入通过的证据。

本轮仅新增本文档，没有程序变更，因此没有新增 TDD 用例或静态类型检查。文档 JSON 与实际 `result.json` 逐字段一致，确认没有 `probe.*` 媒体产物，试验下载器和 Deno 无残留进程。Standards 与 Spec 两个独立审阅均为零发现。未运行 Skill 回归、wheel 安装或生产验收。

## 后续：经现有本地代理与镜像试验

用户随后明确要求尝试非直连或 YouTube 镜像。本节替代前文“没有代理试验授权”的后续限制，只授权本地临时网络试验；不代表部署或修改服务器网络授权。试验时 HEAD 为 `adeeb8498a1765b202431f74260821f64b7bfe1c`。

原 `/tmp/drum-score-youtube-dntge58x` 已不存在，因此重建 `/tmp/drum-youtube-proxy-VccOg2Vi`。仍使用 Python 3.12.12、yt-dlp 2026.10.21、yt-dlp-ejs 0.8.0 和 Deno 2.9.8，实际版本与 Deno 文件摘要均核对一致。GitHub CLI 下载 Deno 时返回 EOF，改为经现有本地代理从同一官方 Release HTTPS 地址下载成功。

仅检查标准代理变量中的地址字段和几个本地端口，不读取代理配置、订阅、凭据或浏览器登录态。发现无认证的本地 HTTP 代理 `127.0.0.1:7890` 可连接。所有试验使用该明确地址，不修改全局网络或代理配置；试验子进程仍使用空白 HOME 和干净环境。

通过显式 urllib `ProxyHandler` 请求同一个 YouTube 视频页面，返回 HTTP 200，读取前 1024 字节，耗时 0.793 秒。这只证明页面可达，不代表媒体可下载。

下载命令沿用上文隔离参数，增加 `--proxy http://127.0.0.1:7890` 与 `--fragment-retries 0`，选轨改为 `bestvideo[height<=360][ext=mp4]/best[height<=360]`。保持 32 MiB 下载上限、10 秒 socket timeout 和零次重试；外层期限为 120 秒，超时按独立进程组终止。本次两次均正常返回失败，没有触发总期限。第二次仅额外指定 `--extractor-args youtube:player_client=android_vr`，验证另一种匿名客户端。

| 下载方式 | 耗时 | 退出码 | 脱敏错误分类 | 媒体文件 |
| --- | --- | --- | --- | --- |
| 显式代理、默认客户端 | 6.303 秒 | 1 | `authentication_or_bot_challenge`、`bot_challenge` | 无 |
| 同一代理、android_vr 客户端 | 6.505 秒 | 1 | `authentication_or_bot_challenge`、`bot_challenge` | 无 |

分类来自 stderr 中身份确认及机器人提示的固定关键词匹配，原始输出只在内存处理，没有保存 Cookie、签名地址或响应正文。临时 `result.json` 和 `android-vr-result.json` 保存脱敏摘要。没有下载文件，因此仍未进行 FFprobe、转换或真实鼓谱验收。当前证据表明该代理可以打开视频页面，但这两次匿名下载遭遇机器人验证，不能笼统归为“国内网络不通”或“yt-dlp 不支持 YouTube”。

镜像备选只探测 [Invidious 官方实例列表](https://docs.invidious.io/instances/)中的两个实例，各请求一次 `/api/v1/videos/jNQXAC9IVRw`，最多读取 128 KiB 加一个检测字节，socket timeout 为 10 秒。多地址尝试可能使实际总耗时超过 socket timeout；这不是外层总期限。没有批量采集或尝试绕过实例认证。

| 实例 | 直连 | 经本地代理 |
| --- | --- | --- |
| `invidious.nerdvpn.de` | `URLError`，20.084 秒 | HTTP 401，1.185 秒 |
| `invidious.tiekoetter.com` | `URLError`，20.087 秒 | HTTP 403，1.642 秒 |

两次直连仅记录了异常类型，没有保存内部原因，不能把它们写成确定的超时或具体拦截。经代理的接口均未取得可用视频 JSON，401/403 也不能推断为整个实例对所有浏览器永久不可用。脱敏结果在临时 `mirrors.json`、`mirrors-proxy.json`。没有取得媒体，不能把公共镜像认定为已可用后端。

[Invidious FAQ](https://docs.invidious.io/faq/)说明，默认播放仍由客户端访问 Google 视频域，启用视频代理才由实例转发。因此镜像页面可打开不等于国内环境可以获取视频。[yt-dlp 的 YouTube 说明](https://github.com/yt-dlp/yt-dlp/wiki/Extractors#youtube)也区分网络、客户端与 PO Token 等限制；本次没有把机器人验证直接诊断为缺少 PO Token。

后续优先在另一个受控、允许匿名下载的出口复测 yt-dlp，或另行评估受控下载节点。公共镜像仍可作为手动备选研究，现有两项探测不足以承诺可靠性。没有切换代理节点、读取 Cookie、引入账号认证或操作服务器。产品接入与前端支持声明继续等待成功下载证据。本节只补充试验文档，未重跑程序全回归或 Skill 测试；上一轮 212 项回归结果不能视为本节的 YouTube 验收。

## 第三轮：重试成功与本地接入

用户要求再试一次后，继续使用现有 `127.0.0.1:7890` 代理和原固定依赖，不修改代理节点或读取登录态。基线为 `2790f0b0e68260643f3dfd2da3dc5fe4fb763c23`。临时证据为 `/tmp/drum-youtube-retry-ONqQbPBJ`，长期本地证据为 `work/engineering/2026-10-24-youtube/`。

| 请求 | 实测结果 |
| --- | --- |
| 原 `jNQXAC9IVRw`、默认客户端重试 | 4.274 秒，身份/机器人验证，无媒体 |
| 原视频、android_vr 且跳过网页等请求 | 5.482 秒，身份/机器人验证，无媒体 |
| 原视频、web_embedded | 2.755 秒，身份/机器人验证，无媒体 |
| 另一公开视频 `dQw4w9WgXcQ`、web_embedded | 12.996 秒，退出 0，下载及 FFprobe 成功 |

另一公开视频的初次两次尝试误写成只有十位的 `dQw4w9WgXc`，被解析器拒绝；其中一次归类为 `incomplete_response`。这是试验输入错误，修正后才得到上表成功结果，不把这两次无效请求当作平台或网络失败证据。

成功试验限定 360p、32 MiB，取得完整视频文件 5685561 字节、640×360 AV1、213.040 秒，SHA256 为 `5ce491450aaf704a59652896965d96e36cf9250822f6f1be8482c93f362d2eb4`。它只验证下载能力，不是鼓谱或音乐验收。

按先前确认的顺序继续接入程序、CLI 和网站。YouTube 只注册自己的 extractor，先尝试 web_embedded，失败后尝试默认客户端；B站保留 BBDownNext。复用原生轨选取、完整曲长/实测分辨率/解码与受限传输。独立 Skill、仓库名称、Python distribution 名称保持不变。

项目安全路径最初发现本机 YouTube DNS 混合返回公共 IPv4 与非公共 IPv6，按旧全地址规则拒绝。YouTube 后续限定 IPv4，仍验证该地址族全部回答并固定公共数值 IP、验证原域 TLS，重定向再次核验；没有忽略私网回答或关闭保护。元数据与媒体均支持标准 HTTPS 代理变量。安装与范围见 [YouTube 指南](../script-product/youtube.md)。

受保护获取路径先在 32 MiB 的小额试验中因最高原生轨超额而受控拒绝。随后一次 400 MiB/180 秒试验匿名解析失败，最终同预算的新试验成功取得完整最高原生轨：

| 项目 | 实测值 |
| --- | --- |
| API | `public_video.acquire`，未替换网络或解析器 |
| 规范来源 | `https://www.youtube.com/watch?v=dQw4w9WgXcQ` |
| 总耗时 | 141.816 秒 |
| 文件大小 | 358608461 字节 |
| 原生视频 | VP9，3840×2160，25 fps |
| 完整时长 | 元数据 213 秒，FFprobe 213.040 秒 |
| 文件 SHA256 | `dbe621f8efea33f941d330202c7da4b68f141be0baceb37b2a3058684b0660c6` |
| 来源记录 | `kind=youtube`、视频 ID、yt-dlp 版本、匿名标记、原生选轨、曲长容差 |

保留的原始文件为本地证据目录中的 `source-youtube-dQw4w9WgXcQ.mp4`，与临时获取文件建立硬链接后核对 hash。另保留脱敏元数据和 `native-source.json`。本次显式使用 400 MiB 获取额度，仅验证独立获取 API；不声称这个 4K/约 342 MiB 视频符合转换默认 256 MiB 和约 420 万像素限制，没有静默降分辨率。

通过一次 `ytsearch3` 找到两条真实《小星星》鼓谱候选，分别使用正式 `convert` 入口测试：`nu9ckSrP-ic` 在 27.172 秒后、`9RwL9af9-Do` 在 29.228 秒后均返回 `youtube_challenge`，无 PDF 发布。结果分别保存为 `real-result.json` 与 `real-short-result.json`。因此真实 YouTube 鼓谱全流程验收仍未通过，没有真实鼓谱页面可查看，也没有新的 PTS/音乐逐符号验收。

本地前端说明 B站与 YouTube，规范化 watch/youtu.be/Shorts，保留 B站分 P；时间戳和播放列表不改变整条 YouTube 来源。真实网络仍可能风控失败，页面与文档保留此限制。没有部署或推送本轮变更。

### 本地验证

程序独立环境执行 `python -m unittest discover -s tests -v`，最终 222 项通过，189.982 秒。首次完整执行有一项取消任务测试因响应缺少 `state` 报错，单独重跑和完整重跑均通过，原因未确定，保留 `regression.log` 与 `regression-final.log`。新增九项 YouTube 测试和三入口公开契约均通过；合成 extractor/媒体不冒称真实网络或音乐验收。

执行 `python ci/verify_script_product.py --output work/engineering/2026-10-24-youtube/replay` 通过，重复转换 PDF 字节一致，输出已存在与资源超额均受控拒绝。JavaScript 语法、六种规范化/拒绝场景、Ruff E701/E702、Python 编译和 `git diff --check` 通过。没有配置静态类型检查器，没有执行浏览器视觉验收或独立 Skill 回归。

从准确源码构建 wheel，三十个包文件逐字节一致，SHA256 为 `855f5a90a65f2a360c2732d873e849e13cdd55ee3698e91902b04fe73099c1fc`。基础与 web extra 分别安装到本地独立环境，依赖冲突检查通过；从仓库外执行 CLI 帮助和合成转换，全部 PDF/预览 hash 与来源 hash 匹配，保持 `reliable=false`。web 环境实际启动安装后的 HTTP CLI，验证首页 YouTube 说明、规范来源提交、查询、取消与独立 worker 启动。报告为 `wheel.json`、`installation.json`、`installed-conversion.json`。本轮没有执行完整 sdist 安装验收。

复核范围覆盖输入规范化、两个后端分流、公共域/DNS/TLS/重定向保护、代理头与认证隔离、响应大小和原生媒体完整性。此前审阅发现 YouTube 整秒时长与 0.5 秒容差冲突，已改为显式 1 秒并增加接受小数尾部、拒绝截断的验证。续跑中派发的独立审查未返回有效代码审查报告，因此这里只记录主执行者自查，未发现新增待修问题，不声称独立双轴审阅通过。
