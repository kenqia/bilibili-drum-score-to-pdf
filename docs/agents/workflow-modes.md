# auto、fast 与 full

新任务使用 `--mode auto|fast|full`。当前默认仍为 full，auto 的目标默认地位需经过真实冷启动交付验收。既有任务继续使用它创建时的证据与接受策略，后续操作无需重复 mode。

| 模式 | 新任务行为 | 待审阅缺口 |
| --- | --- | --- |
| auto | lazy 导航，候选搜索、干净来源恢复、最小接续链、逐项脚本接受可用 | 先替换候选、局部补采与复核；必要时加强同任务原生审阅 |
| fast | 同样从 lazy 开始 | 使用既有补采预算；不自动扩充整包审阅，真实缺口保留 waiting |
| full | 原有 Agent-first 全量视觉观察包 | Agent 实际审阅后提交，不调用旧 convert 保底 |

```sh
uv run --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt skills/bilibili-drum-score-to-pdf/scripts/convert.py /absolute/video.mp4 --output /absolute/task --mode auto
uv run --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt skills/bilibili-drum-score-to-pdf/scripts/convert.py --operation review-plan --task /absolute/task --output /absolute/review-plan
uv run --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt skills/bilibili-drum-score-to-pdf/scripts/convert.py --operation candidate-plan --task /absolute/task --decision /absolute/review-plan/candidate-request.json --output /absolute/candidates
```

auto/fast 预设展开为 lazy、minimum-evidence-chain、evidence-recovery 和 script-acceptance。脚本接受只是可用能力，Agent 可以逐项实际确认不满足自动规则的行。能力开关不自动认定 clear、完整边界或空间身份。旧低层开关保留兼容；full 预设与 lazy 实验参数混用会拒绝。

## 冷启动与复用

首次 prepare 后，review-plan 输出 `candidate-request.json`，绑定当前任务、观察 hash 与版本，包含未确认几何结构。candidate-plan 接受该请求；没有请求和 seed 时也可从当前观察生成建议。实际 PTS、原帧 hash、bbox 和候选状态保留，几何建议不建立已审身份。物化或补采改变观察 hash 后，重建请求。完成候选搜索及替换尝试后再构建最终决定。

已知同一来源的可信任务可明确用 `--reuse-task /absolute/verified-task --mode auto` 创建新任务。这里只检查调用方指定的任务，不扫描历史或任意目录。复用原帧时核对源视频、原帧和已接受记录，并复制视频到新任务的 `source.<原扩展名>`，校验副本 SHA256。旧目录移走后，新任务的来源独立。采样预算与历史 provenance 保留；正面视觉判断不迁移。复制成本计入当前 prepare，可能增加磁盘占用。

## 同任务加强审阅

review-plan 的 `workflow_routing` 给出是否还有自动加强机会。auto 尚缺原生整帧证据、没有硬冲突且未执行过加强时，输出 `strengthen-review-request.json`。先搜索并实际核查已有候选，只有仍需更充分视觉检查才执行。

```sh
uv run --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt skills/bilibili-drum-score-to-pdf/scripts/convert.py --operation strengthen-review --task /absolute/task --decision /absolute/review-plan/strengthen-review-request.json
```

请求字段仅为 `schema_version=1`、当前 `task_id`、`observation_sha256`、`observation_version` 和 `reason`。reason 仅接受 `candidate_shortage`、`native_review_pending`、`layout_unconfirmed`。fast 任务可由调用方显式申请同样的加强，计划不会自动推荐整包扩充。

操作复用已有 ROI，补齐缺失整帧原生区域。最多96张原帧、一个加强轮次，既有600秒解码及8次局部补采预算不重置。已完整覆盖时，只发布一次缓存记录锁定本轮额度。执行前预扣本轮额度，失败或中断也保留，后续只能局部继续或等待。操作计入原生命周期，seek 与导航次数为0；生成图像不等于实际呈交，仍需 Agent 真正审阅并绑定新版决定。

任务继续保持 lazy 的来源、几何、内容、覆盖及脚本接受校验。full 的含义在这里是更充分的原生视觉审阅，不是策略迁移或重新下载。build-decision 与带已确认结构的 review-plan 发现明确内容/对齐冲突时，将首个硬理由摘要保存在任务中，完整比较仍在构建证据文件。该记录跨物化与补采保留，strengthen-review 返回 `hard_evidence_conflict`；实际几何矛盾也保留硬标记。必须直接核查和纠正对应，不能通过更换 mode 解除。来源篡改先由 checked_task 拒绝。

加强完成后，重新生成候选/构建请求并实际审阅新增范围。证据充分才 build、submit、export、逐页 confirm-delivery。按验证需要 replay，不在日常流程无条件重复计算。预算耗尽仍 waiting，全部失败操作、成本未知字段及污染比较保留。

## 默认放行与回退

当前软件测试证明接口、缓存、预算和门禁行为，不能代替不同歌或全新链接的真实视觉交付。真实冷启动尚未验收时保留 full 默认，允许显式 auto/fast。关闭 mode、在新目录运行默认 prepare 即可回到 full；保留旧任务，不迁移它的策略。已安装 skill 的同步另行管理，本次仓库文档变化不会自动修改安装目录。
