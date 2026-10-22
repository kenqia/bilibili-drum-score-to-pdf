# 独立转换核心与 CLI

本页说明独立程序的 Python 与 CLI 入口。Skill 使用自己的[分发包和协议](../../skills/bilibili-drum-score-to-pdf/SKILL.md)，不与程序共享任务状态。程序通过图像处理整理视频，不调用模型，也不创建 Agent 审阅回执。自动完成不表示音乐已校对。

Issue #71 的本地资源模拟为每次转换建立独立 worker 和任务临时目录。父进程监督整个任务，PDF、预览和清单全部准备好后由父进程排他发布。Linux 守护进程在调用方异常退出后清理本次任务；它只删除启动时记录 inode 身份的目录。Windows 尚无本轮异常退出清理验收。

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

程序使用固定 BBDownNext 2.3.0 解析匿名播放信息，替代 yt-dlp。安装与平台要求见[安装指南](../install.md)。不读取用户 Cookie、登录态、模型认证或下载器用户配置；不使用 VPN，也不继承用户代理。输出目录必须不存在；失败后换新目录或重试，不覆盖来源及已有结果。删除独立虚拟环境即可撤销安装，不修改全局配置。

每次解析使用通过摘要校验的独立可执行文件副本和空配置。来源 BV、目标分 P、CID、完整曲长和受限标记必须可验证，拒绝互动、跳转、试看或不完整来源。部署使用 2.3.0 的 `metadata-bounded.1` 构建，普通调试响应与 HTTP 响应均设 2 MiB 上限。若必要来源响应缺失或被截断，程序明确失败，不以标题或退出码推断完整性。原始解析输出不进入日志、结果或诊断；临时播放 JSON 仅在本次私有目录读取，解析后删除。发布记录保留安全的后端名称、版本、构建名称及摘要、CID 和媒体实测信息。

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

结果使用 JSON 可序列化字典，`status=complete`、`reliable=false`。`pdf`、有序 `pages`、`longshot` 包含输出目录相对路径、SHA-256 与字节数；`source` 区分本地来源和公开 BV/分 P；`samples` 记录实际解码 PTS、time_base、时间与原生帧 hash。派生长图不称为原生截图。来源文件移除后不得宣称仍可重建原始帧。 原生帧按解码器实际输出顺序观察，末尾延迟帧的PTS可能小于前一帧；程序保留这些实际值，不按PTS重排或重新赋时。诊断完整性检查使用原生序号及每帧统计、采样PTS的配对，不要求所有原生PTS单调。

`manifest.json` 与 Python 返回值及 CLI 成功标准输出相同。`program` 记录发行版本与包内直接子级 Python 源码文件的 SHA-256，不包含网站静态资源，不能当成整个发行产物的 hash，未安装包的源码运行以 `unknown` 表示未知发行版本。CLI 失败退出码为 2，JSON 包含 `status=failed` 和 `error.code/message`。错误不返回第三方原始异常、签名媒体地址或本地私有路径。

输出父目录创建或临时目录分配失败时，Python 抛出 `ConversionError`，CLI 返回 `conversion_failed` JSON 和退出码 2。临时目录清理失败不会覆盖已有具体错误码，也不会撤回已完整发布的成功结果。

## 资源预算

默认支持不超过600秒、单帧420万像素、派生长图2000万像素的视频。原视频上限256MiB；单任务临时文件与进程树RSS各使用1GiB采样预算。超过预算返回 `resource_limit`，取消返回 `cancelled`。既有来源和输出不覆盖。

CLI 可调整总时限和字节预算：

```sh
drum-score /absolute/path/input.mp4 --output /absolute/path/new-result \
  --timeout 600 --max-input-mib 256 --max-temp-mib 1024 --max-rss-mib 1024
```

Python 的 `convert` 接收 `limits` 字典，字段为 `wall_seconds`、`input_bytes`、`temp_bytes`、`rss_bytes`，只覆盖提供的字段。`cancel` 接收无参数函数；返回真时取消任务。`progress` 和 `cancel` 在调用进程执行，转换在新解释器执行。可执行 Python 脚本应把调用放在 `if __name__ == '__main__':` 保护内。`complete` 回调发生在发布后，回调异常不会撤回成功结果。

进程树RSS约每20ms采样，临时文件总额约每200ms扫描。采样可能漏掉瞬时峰值或短暂超额，RSS求和可能重复统计共享页；它们都不是cgroup或文件系统硬配额。`resources` 记录实际采样方式、峰值、线程环境与额度，未知值为 `null`。`metrics.peak_temp_disk` 仍只指旧解码器单张scratch帧大小，任务总临时空间应读 `resources.peak_observed_temp_bytes`。

OpenCV设置单线程，子进程环境将常用数值库线程变量设为1；不修改用户全局环境。五线与分页空白计数使用256行缓冲，合成仍保留一张有像素上限的RGB长图。当前环境没有可写cgroup和systemd用户管理器，以上是本机预算模拟，不能证明目标2GB服务器已通过。

## 支持边界与验收

目标输入为固定比例、白底纵向滚谱，包括停驻后向上推进。简单翻页尚未列入支持。检查到无法配准、没有五线谱或来源变动时明确失败；程序不能自动识别全部不适用布局。

相邻原始画面逐像素一致时才考虑停驻；其他画面比较向前配准候选。相似谱行中的小节号也参与比较，避免把不同原谱位置的重复音乐合并。

固定0.5秒采样可能恰好跨越完整的重复系统，使两个采样看起来相同。程序在同一次流式解码中分出运动观察支路，将每个原生帧等比缩至最大128×128，测量相邻原生帧的8位亮度平均绝对差。原始RGB取样支路不经过该缩放或颜色转换。每个采样间隔只保留最大亮度差、原生序号和实际PTS的有界摘要，不新增seek，不保存高频RGB或原生日志。

存在被跳过的原生帧且亮度平均绝对差超过1时，程序要求采样之间的位置可区分。如果多个相隔超过2像素的位移具有同等全局及局部匹配质量，程序返回 `discontinuity`，不靠偏好最小位移选择其中一个；精确相同的采样也必须经过这项候选检查。这覆盖跨越一个或1.5个重复系统的周期采样别名。

亮度变化本身不证明发生滚动；存在唯一可行位置时，即使背景或播放标记变化，程序仍按该位置接续。取样已包含每个原生帧时保留原有相邻配准，不宣称能恢复源视频在原生帧之间未记录的运动。运动检查不改变采样间隔，不猜测遗漏的谱行数。

128像素缩图、亮度差1和候选位置相隔2像素是通用启发式边界，不保证检测所有运动。背景或播放标记发生明显变化，也可能触发保守拒绝；很小的运动可能被缩小或阈值漏掉。该观察不能代替SHA-256来源完整性证据或音乐校对。诊断逐行读取并立即丢弃，每次读取最多4096字节。持久采样和运动摘要仍受4097条上限、解码期限和任务磁盘额度约束。结果 `metrics.native_motion_observations` 记录原生观察数，`samples` 的 `native_motion_max_luma_difference` 记录采样间隔最大变化，`native_intermediate_frames` 记录未保留为RGB的原生中间帧数，最后一个常规采样另记录尾段摘要；`decoded_reported_frames` 仍统计实际返回的采样与读帧记录。

彩色记号、水印及播放标记可能保留。清理不能证明隐藏符号正确，结果无警告也不能证明音乐等价。分页仅在检测到的安全空隙间处理完整谱行或连续行组，并保持比例；超高组不得硬切。

A4 默认页边距为12点，约4.23毫米。同一份谱面使用统一比例，先确定可容纳完整行组的最少页数，再均衡各页连续条带的高度，避免前页填满而尾页仅剩少量内容。不会通过改变原行距、横向拉伸或裁断行组填满页面；单页短谱仍可能保留底部空白。

合成视频用来验证公开输入、输出保护、来源时间、比例与分页约束，不代替真实谱面质量验收。固定真实集的版本、hash、首轮基线和回归证据由比较工具记录，未知指标保留 null。
