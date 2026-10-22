# 安装程序

使用独立虚拟环境安装 CLI；运行匿名网站时增加 `web` 可选依赖。安装不修改 Codex、认证、shell 配置或已安装 Skill。

## 前置条件

需要 Python 3.12 或更新版本、FFmpeg 与 Poppler。公开 B站链接另需固定 BBDownNext 2.3.0；本地视频转换不需要它。当前验证环境为 Python 3.12；网站 worker 使用 Ubuntu/Linux 的 `/proc`、`flock` 和文件描述符语义。Windows 只提供本地视频 CLI 与媒体工具兼容性测试，不承诺 Linux 服务生命周期。

Ubuntu 可在自己的环境安装 `ffmpeg`、`poppler-utils`、`fonts-dejavu-core`。确认 `ffmpeg -version`、`ffprobe -version`、`pdftoppm -v` 成功。开发验证另需 `pdfinfo` 和 `pdfimages`。

## 安装公开链接解析器

当前公开链接支持 BBDownNext 2.3.0 Linux x64 的 `metadata-bounded.1` 构建，已在 WSL Ubuntu 22.04 编译，目标运行环境为 Ubuntu 24.04 x86_64。它不会随 Python wheel 安装。其他平台或未经验证的可执行文件不作为本轮公开链接支持；不要跳过摘要或 TLS 校验。

该构建基于[准确的上游 v2.3.0 源码](https://github.com/KaiHuaDou/BBDownNext/tree/v2.3.0)，仅把普通调试 JSON 上限从 8192 字符调整为 2 MiB 字符，把 HTTP 响应读取上限从 64 MiB 收紧为 2 MiB。原版调试截断会使必要来源信息不完整。下载、匿名接口与 TLS 逻辑沿用上游。构建补丁、许可与来源记录见 [BBDownNext 构建说明](bbdown-build.md)。

从交付包取得 `BBDown` 后核验摘要，再复制进专用虚拟环境的 `bin/BBDown`。下面的目录须替换成自己的独立环境。目标文件必须不存在，不覆盖旧版本。

```sh
printf '%s  %s\n' 'd5fe48f6c2bf2e388937d3c8985c1e3dcca678e5a8d8345fa5c31e36793baf0a' '/absolute/path/BBDown' | sha256sum --check
test ! -e /absolute/path/drum-score-env/bin/BBDown
install -m 0755 /absolute/path/BBDown /absolute/path/drum-score-env/bin/BBDown
```

程序每次验证可执行文件摘要，只复制这一个文件到新任务目录，不读取安装位置旁的配置或凭据。不要复制 `BBDown.data` 或 `BBDown.config`，不要登录。解析器仅在匿名公开信息范围工作，可能向公开接口申请临时设备标识。结果记录实际构建名称和摘要。原始官方 Linux x64 摘要也可识别为 `official`，但来源 JSON 截断时仍拒绝转换；实际部署采用上述有界构建。

解析请求通过任务私有回环 CONNECT 校验中继，逐次验证全部 DNS 地址并固定数值 IP。TLS 仍由 BBDownNext 端到端校验；上游由本机直连，没有 VPN、系统代理或全局路由修改，也不继承用户代理变量。媒体传输继续使用已有公共地址与 TLS 校验。没有启动 BBDown `serve` 或第二个任务队列。第三方许可见 [BBDownNext MIT 许可](licenses/BBDownNext-MIT.txt)。

## 安装与核验

在源码仓库创建专用环境：

```sh
python3.12 -m venv /absolute/path/drum-score-env
/absolute/path/drum-score-env/bin/pip install /absolute/path/bilibili-drum-score-to-pdf
/absolute/path/drum-score-env/bin/pip check
/absolute/path/drum-score-env/bin/drum-score --help
```

Windows 使用环境内的 `Scripts/python.exe`、`Scripts/drum-score.exe`。不要把 WSL 与 Windows 的虚拟环境混用。

网站改用 `pip install '/absolute/path/bilibili-drum-score-to-pdf[web]'`，再核验 `drum-score-web --help`、`drum-score-worker --help`。基础安装不依赖 FastAPI 或 Uvicorn，页面资源随 wheel 安装。服务启动见[网站运行指南](script-product/website.md)。

在仓库外用一个清晰测试视频运行 `drum-score /absolute/path/input.mp4 --output /absolute/path/new-result`，检查成功 JSON、PDF 和全部预览。此检查验证安装及工具调用，不证明真实音乐准确性。

## 升级与回滚

在另一个虚拟环境安装新版本，验证后再切换运行入口。服务升级前停止 HTTP 和 worker，保留同一时点的数据库、结果文件和准确发行版本。SQLite `user_version=1` 是当前服务 schema；未版本化旧库及未知版本会被拒绝，不自动迁移旧任务。

回滚时同时恢复匹配版本的程序和完整数据副本，不让旧代码打开未知 schema。复制到新目录会改变 inode 与 ctime，恢复工具必须在核验文件清单与 hash 后，为自己新建的文件重新登记受管身份，原完成与到期时间保持不变。不要直接复制旧所有权字段并声称清理仍有效。停服备份、只读核验与恢复使用随基础包安装的 `drum-score-maintenance`，步骤见[维护指南](script-product/maintenance.md)。部署模板与离线依赖归档见[部署指南](script-product/deployment.md)。

独立环境可通过停止对应进程和停用该环境撤回，不删除用户输出或其他服务目录。旧 Skill 安装与旧任务由用户单独保存；本项目不自动卸载或迁移它们。
