# 发布与决定重验的内部重构

2026-10-12，用户确认先集中两项内部编排，再冻结首发实测版本。比较基点为 `8d86471b99b0f56f72afae02f46a06b227fb3115`。命令、任务协议、决定格式、模式默认值和审阅权限保持原有行为，不增加生产依赖或可插拔存储。

## 观察包发布

`agent_publication.publish` 接收观察包、当前采样账本和待发布任务状态。这个 module 写入三份 `.next.json`，计算观察与预算 hash，绑定 task 记录，再写入 publication journal。`recover` 按 observation、sampling、task 的顺序核对并替换文件，全部完成后才删除 journal。`prepare` 与 `materialize` 共用这个 interface，调用方负责生成观察、保存旧观察归档和证据请求。

恢复向前完成发布。后部文件损坏时，前部可能已经替换，journal 继续保留；不会清理真实原图、撤销已生成成本或退还失败补采预算。已审前缀、接受历史、实际 PTS 和来源 hash 继续由现有任务检查验证。性能账本独立保存，不属于这三份记录的同一事务。

## 接受决定重验

`agent_decision_review.review` 从新提交旁记录或已接受历史读取依据，按 acceptance、continuity、validate、audit 的顺序重算。这个 module 隐藏门禁组合，返回所选裁剪、内容检查、接受记录和审计。`agent_acceptance`、`agent_evidence_chain`、`agent_audit` 各自保留原有规则；重复 submit、新 submit、export 和 replay 复用编排。

新提交仍绑定精确文件字节，v5 仍检查累计前缀与显式修订。普通全视觉历史重复提交在来源核对和 JSON 相等后返回；混合决定或最小证据链重复提交继续核对精确 hash 并重验旁记录。重复提交不增加原先没有的验证计量阶段。export/replay 每次重验后再核对原视频、重解码和生成 PDF。

`build-decision` 保留独立的草稿 probe、疑点收集和等待语义。构建成功不会写接受历史，也不能把 probe 的临时视觉权限当成真实审阅。内容只否决冲突，身份仍由完整五线几何和空间顺序验证。

## 验证与回滚

已确认的 seam 是统一 CLI。恢复测试覆盖三份文件替换的每个中断状态、后部损坏后继续发布和接受历史保留；证据测试继续验证原图、symlink 拒绝、旧决定拒绝和失败成本。决定重验复用审计、混合接受、最小证据链、原帧恢复及决定构建的正负例。

相关单文件验证后，在最终源码上运行一次完整 unittest。随后使用标准 BV URL 独立双跑，分别实际审阅、核对来源与 PDF，并检查各自保存决定重放。新鲜记录写入 verification.md，不用旧决定代替新的视觉判断。

回滚使用基点提交的独立 checkout 和新结果目录。保留当前任务、决定与实验记录，不将新任务自动迁移到旧代码。
