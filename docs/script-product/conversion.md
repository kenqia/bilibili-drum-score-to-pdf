# 独立转换核心与 CLI

本页说明 Issue #70 的程序入口。旧 Skill 在本票继续保留。新程序通过图像处理整理视频，不调用模型，也不创建 Agent 审阅回执。自动完成不表示音乐已校对。

## 安装与运行

需要 Python 3.12 或更新版本，以及 PATH 中的 `ffmpeg`、`ffprobe`、`pdftoppm`。在独立虚拟环境安装，避免改变其他项目依赖：

```sh
python3.12 -m venv /tmp/drum-score-env
/tmp/drum-score-env/bin/pip install /absolute/path/to/bilibili-drum-score-to-pdf
/tmp/drum-score-env/bin/drum-score /absolute/path/input.mp4 --output /absolute/path/new-result
```

安装复制所需代码，运行不依赖源码仓库的当前目录。公开链接使用规范 HTTPS BV URL，分 P 通过单个正整数 `p` 指定：

```sh
drum-score 'https://www.bilibili.com/video/BV1rH4y1R7Rk?p=1' --output /absolute/path/new-result
```

程序复用原有匿名下载器。不读取 Cookie、登录态、模型认证或下载器用户配置。输出目录必须不存在；失败后换新目录或重试，不覆盖来源及已有结果。删除独立虚拟环境即可撤销安装，不修改全局配置。

## 公开 Python 契约

```python
from drum_score import convert, ConversionError

try:
    result = convert('/absolute/path/input.mp4', '/absolute/path/new-result',
                     progress=print)
except ConversionError as error:
    print(error.code, str(error))
```

`progress` 接收正在执行的阶段名，包括 `downloading`、`probing`、`sampling`、`registering`、`composing`、`paginating` 和 `complete`。本地输入跳过下载。没有可靠百分比和预计时间。转换阶段的回调异常会使转换失败；`complete` 在结果发布后通知，通知异常不会撤回已发布结果。

结果使用 JSON 可序列化字典，`status=complete`、`reliable=false`。`pdf`、有序 `pages`、`longshot` 包含输出目录相对路径、SHA-256 与字节数；`source` 区分本地来源和公开 BV/分 P；`samples` 记录实际解码 PTS、time_base、时间与原生帧 hash。派生长图不称为原生截图。来源文件移除后不得宣称仍可重建原始帧。

`manifest.json` 与 Python 返回值及 CLI 成功标准输出相同。`program` 记录发行版本与转换包源码文件的 SHA-256，未安装包的源码运行以 `unknown` 表示未知发行版本。CLI 失败退出码为 2，JSON 包含 `status=failed` 和 `error.code/message`。错误不返回第三方原始异常、签名媒体地址或本地私有路径。

## 支持边界与验收

目标输入为固定比例、白底纵向滚谱，包括停驻后向上推进。简单翻页尚未列入支持。检查到无法配准、没有五线谱或来源变动时明确失败；程序不能自动识别全部不适用布局。

彩色记号、水印及播放标记可能保留。清理不能证明隐藏符号正确，结果无警告也不能证明音乐等价。分页仅在检测到的安全空隙间处理完整谱行或连续行组，并保持比例；超高组不得硬切。

合成视频用来验证公开输入、输出保护、来源时间、比例与分页约束，不代替真实谱面质量验收。固定真实集的版本、hash、首轮基线和回归证据由比较工具记录，未知指标保留 null。
