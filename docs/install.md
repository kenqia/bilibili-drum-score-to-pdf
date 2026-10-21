# 安装程序

使用独立虚拟环境安装 CLI；运行匿名网站时增加 `web` 可选依赖。安装不修改 Codex、认证、shell 配置或已安装 Skill。

## 前置条件

需要 Python 3.12 或更新版本、FFmpeg 与 Poppler。当前验证环境为 Python 3.12；网站 worker 使用 Ubuntu/Linux 的 `/proc`、`flock` 和文件描述符语义。Windows 只提供 CLI 与媒体工具兼容性测试，不承诺 Linux 服务生命周期。

Ubuntu 可在自己的环境安装 `ffmpeg`、`poppler-utils`、`fonts-dejavu-core`。确认 `ffmpeg -version`、`ffprobe -version`、`pdftoppm -v` 成功。开发验证另需 `pdfinfo` 和 `pdfimages`。

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

回滚时同时恢复匹配版本的程序和完整数据副本，不让旧代码打开未知 schema。复制到新目录会改变 inode 与 ctime，恢复工具必须在核验文件清单与 hash 后，为自己新建的文件重新登记受管身份，原完成与到期时间保持不变。不要直接复制旧所有权字段并声称清理仍有效。备份恢复工具属于后续部署交付，当前安装命令不自动执行恢复。

独立环境可通过停止对应进程和停用该环境撤回，不删除用户输出或其他服务目录。旧 Skill 安装与旧任务由用户单独保存；本项目不自动卸载或迁移它们。
