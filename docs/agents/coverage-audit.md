# 整曲与行外区域审计，实验 lazy 入口

2026-10-10，本轮只实施软件与合成验证。默认 `full` 及旧决定重放保留原行为，真实基线和快路径放行条件不变。

实验 `lazy` 任务必须使用带原生来源的 v4 图块和绑定决定的整曲审计。手写 v1、v2、v3 决定返回 waiting，提示经 `build-decision` 升级。连续长谱的 v3 proposal 在完成原有 corrections 和 confirmations 后包装成单段 v4，段 ID 为 `score-000`；原 v3 字段路径不改变。需要标题或独立符号时，提交 v4 proposal 的显式 extras。脚本不再为 lazy 导出使用 `analysis.header_bbox`。

流程沿用 `prepare --evidence-mode lazy`、`materialize`、必要的局部 `supplement`、`build-decision`、`submit` 和 `export/replay`。builder 输出 `decision.json`、差异、来源、未决事项和 `audit.json`，构建本身不接受决定。审计绑定 task、观察 hash 和决定文件的精确 SHA256。提交时二者放在同一目录，禁止替换或重新序列化决定文件。

`review.score_audit` 包含 `segments`、`intervals` 和 `unresolved`。段顺序与 v4 proposal 一致，每段仅含 `id`、`checks`、`first_edge`、`last_edge`。`checks` 必须逐项覆盖 `title`、`tempo`、`time_signature`、`outside_rows`，每项如下。

| 字段 | 含义 |
| --- | --- |
| `status` | `checked`、`absent` 或 `pending` |
| `regions` | 已呈交的原生核查区域，非 pending 项不可为空 |
| `print_regions` | `[{"kind":"row或extra","index":0}]`，索引属于当前段 |
| `evidence` | 简短公开依据，不能用一个 true 替代 |

每份 region 只含 `frame_id`、整数原生 `bbox`、`evidence_images`。细节图必须来自同一帧、实际呈交、映射比例为 1，并完整覆盖核查 bbox。checked 项须由指定的打印 row/extra 完整包含核查区域，来源帧必须相同。包含检查使用 `agent_regions` 校验后的实际执行 bbox；指定 refinement 时使用其最终 bbox，不能用精修前的建议框代替。精修缩掉已核查区域时保持 waiting，未核查的精修也不能成为打印依据。checked title 必须打印为 `kind=title` 的 extra。absent 也须有实际原生核查依据，`print_regions=[]`，空 extras 本身不表示不存在。pending 保持 waiting。

边缘核查包含 `complete`、`regions`、`evidence`，来源分别为当前段首帧和末帧，缺少完整边缘不能完成。intervals 严格覆盖当前已审前缀的全部相邻帧，每项含 `from_frame`、`to_frame`、`status`、`regions`、`evidence`；status 为 checked 或 pending，checked 必须有两端原生证据。已有五线几何、至少两个有序对应、完整干净原行、单帧来源和 DPI 门禁继续执行。换页仍由 v4 boundaries 检查，跳页、回跳、比例变化及缺少完整边界不能导出。

审计计算首尾实际 PTS、源 hash、视频时长、各相邻 gap、接受实例次序、谱面段与边界、核查区域及未决风险。`hidden_content_proven_absent=false` 始终保留。实际审阅声明不能证明模型理解了每个区域，也不能证明未采样时间没有隐藏换谱。

导航达到上限时，原 `sampling.unresolved` 文本保留为历史。不能删除文本或修改预算来放行。现有导航限额风险可通过可选 `navigation_resolution` 声明处理当前已审范围，它严格含 `status`、`new_frames`、`intervals`、`evidence`。status 为 pending 或 reviewed_after_supplement。后者必须引用实际 supplement 发布、区别于初始观察的新增 PTS，有已呈交原生证据，并逐一绑定当前全部相邻帧 gap 的 checked 核查。没有新增 PTS、漏掉当前 gap 或只有文字声明时继续 waiting。未知导航风险不能用此入口解除。报告同时保留历史导航 flag、当前解除声明及源证据，不能把解除声明写成无隐藏内容证明。

submit 将审计保存为独立的 `accepted-...audit.json`，在接受历史中记录路径与 hash。export/replay 重新核对当前 task、观察、决定、原生来源和计算结果。已接受审计篡改、旧决定或旧包审计会拒绝。materialize、supplement 和显式 revision 改变绑定后，需要新审计，历史副本保留；已审前缀可接受，未审尾部仍 waiting，不能提前导出整曲。

`coverage_audit` 阶段计入既有性能账本。补采继续使用原 8 次请求、32 请求帧、96 原生帧、600 秒解码与每次 30 秒局部范围上限。预算耗尽保留来源与 waiting，不能生成成功 PDF。宿主模型计量不可见时仍保留 null。

来源区域 ID 同时绑定 frame ID、源与原帧 hash、实际 PTS、time_base 和 bbox。导航中不同 frame ID 偶然指向相同实际 PTS 时，它们仍保持各自证据引用；相同 frame ID 与 ROI 的重复请求继续复用。
