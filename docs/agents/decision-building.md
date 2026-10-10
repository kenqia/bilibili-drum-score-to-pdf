# 用修正构建决定

`build-decision` 把当前观察包的几何建议、必要修正和 Agent 明确确认写成现有决定协议。它不接受决定，不输出 PDF，也不启用自动审阅。Agent 仍须实际查看原图和完整原生细节。脚本建议不能证明已经看图。

```sh
uv run --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt skills/bilibili-drum-score-to-pdf/scripts/convert.py --operation build-decision --task /absolute/task --decision /absolute/corrections.json --output /absolute/new-draft
```

输出目录必须为空。成功构建返回 `ready_to_submit=true`，随后把其中的 `decision.json` 交给原有 `submit`，再用 `export` 或 `replay` 导出。构建等待时保留草稿，不能直接交付。

## 请求

请求使用独立 `schema_version=1`，绑定当前任务、观察 hash 和观察版本。这不是新决定协议。下面的 `review` 是调用方已经完成实际审阅后的明确声明，示例值不能照抄为实际证据。

```json
{
  "schema_version": 1,
  "task_id": "当前 task_id",
  "observation_sha256": "当前观察包 SHA-256",
  "observation_version": 1,
  "decision_id": "review-1",
  "model": {"id": "实际可见模型标识", "version": "unknown"},
  "prompt": {"version": "review-1", "text": "实际公开审阅任务"},
  "corrections": [],
  "review": {
    "identity_verified": true,
    "coverage_verified": true,
    "outside_rows_verified": true,
    "presented_images": ["实际呈交的图像 ID"],
    "visual_review": true,
    "complete": true,
    "evidence": "实际看到的首尾、接续、标题和覆盖依据",
    "unresolved": [],
    "rows": {
      "complete": true,
      "cursor": "clear",
      "occlusion": "clear",
      "boundary_verified": true,
      "evidence": "实际核查全部所选原生裁剪的依据"
    },
    "observations": {
      "complete": true,
      "evidence": "实际核查全部五线观察的依据"
    },
    "transitions": {"evidence": "实际核查所有相邻对应的依据"}
  }
}
```

`review.rows`、`review.observations`、`review.transitions` 把调用方明确给出的判断应用于各自全部记录。没有给出的判断保持未确认。如果只有部分记录可以确认，请使用 `review.confirmations` 的逐项路径。不能用统一确认掩盖 partial、遮挡或未知接续。

默认建议来自检测器保存的五线几何和空间顺序。相邻对应需要至少两条有序重叠、相同比例、相近横向布局和共同非负位移。多个同样合理的位移或缺少五线几何保留疑点。候选 hash、音乐内容和颜色不建立身份；检测建议可能遗漏行外符号，必须核查原图。

复杂 v2、v3、v4 决定可提供可选 `proposal`。其中只放 `schema_version` 和对应协议的结构字段：v2 的 `rows`；v3 的 `rows`、`observations`、`transitions`、`coverage`；v4 的 `segments`、`boundaries`、`coverage`。请求外层负责绑定当前包。建议中原有的正面判断不会自动沿用。

## 修正与确认

`corrections` 是有序替换列表，每项只含 `path` 和 `value`。路径是字符串键或非负数组下标组成的列表，必须引用已经存在的结构字段。不能创建未知字段、修改协议版本，或直接设置视觉确认。例如调整首行裁剪时，v3 还须同步修正它的身份观察框。

```json
[
  {"path": ["rows", 0, "bbox"], "value": [74, 180, 1206, 320]},
  {"path": ["observations", 0, "bbox"], "value": [74, 180, 1206, 320]}
]
```

`review.confirmations` 使用相同路径格式，只能设置明确视觉判断及原生细节引用。它在统一确认之后执行，可记录某条行、某段行外区域或某个换页边界的实际判断。

```json
[
  {"path": ["rows", 0, "complete"], "value": true},
  {"path": ["rows", 0, "boundary_verified"], "value": true},
  {"path": ["rows", 0, "evidence"], "value": "实际观察到完整符杆、连线和行下力度"}
]
```

ROI、bbox、所选 observation 和 evidence_images 都仍受现有提交校验。未知引用、旧包绑定、非法字段及越界裁剪返回 failed。没有实际确认、细节不足、几何冲突或覆盖不明返回 waiting，草稿的 `complete` 保持 false。脚本不会补写实际呈交记录。

## 保存进度与来源

存在接受历史时，可以省略 `proposal`，以最新接受结构为基础。必须提供 `revision_of`，明确引用最新已接受的外层决定 ID，并使用新 `decision_id`。构建器重新校验，不修改历史。默认清空基础决定的视觉判断，要求本次显式确认。纯证据物化后需要沿用未改的实际判断时，显式设置 `reuse_accepted_review=true`；来源核验与清空条件见 [疑点审阅](review-plan.md)。

可选 `reviewed_frames` 是从首帧开始的连续前缀。前缀或修订输出现有 v5 封装，内部仍为 v2、v3 或 v4。部分进度只允许 v3、v4。旧任务不自动迁移，物化或补采后的修订必须绑定新观察 hash，并明确声明本次实际查看的图像。

lazy 任务另需填写 `review.score_audit`，契约见 [覆盖审计](coverage-audit.md)。原 v3 proposal 在确认后包装为单段 v4；独立标题与行外区域通过 v4 extras 指定。构建输出增加绑定决定文件的 `audit.json`，提交时与决定放在同一目录。缺少审计或直接提交旧版 lazy 决定会等待；full 的既有协议行为保留。

目录保留 `decision.json`、`diff.json`、`sources.json`、`unresolved.json`。差异逐项列出结构与判断的前后值；来源记录当前观察绑定、建议来源、接受历史 hash、五线建议、实际 PTS、源帧 hash 和调用方确认。未知模型版本使用 `unknown`，没有可信模型成本时仍为 null。

`build-decision` 操作和 `decision_building`、`decision_validation` 阶段进入统一性能报告。构建成功只说明决定已经准备好提交，不能结束任务的交付计时，也不证明模型理解了每张图像。

## 本地验证

```sh
uv run --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt python -m unittest discover -s tests -p test_decision_builder.py -v
```

合成验证覆盖未确认草稿、统一确认和少量裁剪修正、严格字段和来源校验、已有协议、前缀恢复、显式修订、历史保留及 PDF 重放。该验证不调用模型，不证明真实视频视觉质量或端到端提速。真实基线和自动接受门禁仍保留。

2026-10-09，首次专项运行因 CLI 不认识 `build-decision` 失败。添加入口后未确认草稿通过。统一确认与非法后部字段的负例随后失败，补上严格校验后通过。替换对象里的非法完整性值、没有五线几何的空白片段也分别先失败，再验证修复。

最终专项 9 项通过，耗时 34.752 秒。v2、v3、v4 都通过构建、提交、导出和保存决定重放；v5 前缀与显式修订保留接受历史。两份同输入构建的四个公开 JSON 文件逐字节一致。`git diff --check` 和新增模块编译检查通过。完整仓库回归由集成分支另行执行，本票没有下载真实视频、调用真实模型或调整默认启用范围。

显式 lazy 任务的几何对应还受[局部内容门禁](content-checks.md)约束。构建、提交、导出与重放都检查当前原生来源；内容冲突或不可靠证据保持 waiting，调用方确认不能覆盖。full 任务保持原验证边界。
