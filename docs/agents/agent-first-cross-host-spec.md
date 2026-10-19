# Agent-first 跨宿主修复规格

2026-10-19，基线 main `9cece50dcfe78affd6f8739c3221521d8bdbf55d`。用户提供的修复说明与[采访决定](agent-first-cross-host-interview.md)共同定义本轮范围。本文是实施与审阅依据，不是实测通过声明。

## 默认流程与审阅

prepare 探测视频、持久化任务并报告宿主依赖状态。stage 默认 mode=agent，未冻结时返回已有截图、首尾采样建议、安全请求字段和来源下一步，不启动 sparse/strict，不自动批准未确认来源，也不生成模型看图记录。

Agent 执行 navigate/capture，实际查看原生图，再 present 与 assemble。每个原谱位置使用明确 position。同位置由 Agent 选择更好来源并去重，不同位置重复音乐保留。新契约要求标题、音乐起点、末行和逐个相邻完整谱行的结构化证据；没有编号时使用其他可见依据，不虚构小节号。源引用绑定当前截图与裁剪，所选原生图必须有 present 声明。

自动检查原记录保留，Agent 对相关疑点逐项登记处理依据。整体 complete 不能替代处理。安全、来源 hash、实际 PTS、裁剪完整性、隐藏音乐未决与全部 PDF 页面审阅门禁保留。自动导航失败本身不禁止合法 Agent 冻结，自动检查不能代替实际看图。

冻结后默认 stage 不重扫，执行 crop-checks 并返回生图/矢量 handoff。无真实生图工具时 redraw-inputs 后逐组 fail-redraw(outcome=unavailable)，记录理由，不伪造调用；合法已有尝试先恢复，不重发。导出全部有序预览，review-pdf 绑定当前独立 output_revision、全部页码和实际审阅依据；缺页、损坏或过期版本拒绝批准。

显式 stage(mode=sparse) 与 stage(mode=strict) 保留原行为、资源期限、各自 provenance 与实际覆盖范围。显式 strict 即使已有稀疏或人工冻结仍执行原扫描语义，不能因默认切换而跳过。

## 兼容与局部恢复

已有合法人工冻结且来源未变时兼容恢复，保留有效生成、修正预算与 PDF 审阅；改变旧工作流来源后按新契约补充受影响位置及相邻接续证据。不迁移旧协议任务。

提供补采纳入候选、局部重叠确认、局部替换或插入位置、局部裁剪及简明 next 字段。局部修改通过现有任务生命周期原子发布，只使直接依赖的派生产物失效。保持输入版本身份、未知调用、一次修正预算、A→B→A 恢复和不覆盖旧文件等规则，不为单个疑点重建全份选择。

## 跨宿主基础缺陷

- 安装器全部文本读写明确 UTF-8，git archive 使用 CANONICAL.as_posix()，清单键采用相对 POSIX 路径。旧清单的安全校验、安装校验、备份、回滚和非管理文件保护保留。
- 接续比较对夹杂 start_bar=None 不做混合数值比较。编号不足或不递增时返回详细未决，只在编号与可见匹配安全时批准编号接续。覆盖局部 fallback、可读编号与残行。
- CLI 错误保留稳定 code，区分 invalid_request、source_review_required、invalid_state、decode_failed、internal_error 等；意外执行异常不能归为用户请求错误。只返回受控 field、operation、action，不暴露请求体、令牌、原始异常或完整私有路径。
- 两个 FFmpeg 读取入口共用能力选择，只在二进制支持时用 fps_mode，否则保留旧版可用的 vsync 0。通过模拟能力矩阵验证旧/新版，并实际检查合成 PTS。
- 无关 Skill 不可读时报告 warning 并继续发现目标。依赖就绪与真实解码功能证据分开；解码探测显式、有限时、匿名且无网络。
- 详细 JSON 保持默认，新增 --output-format summary 与 --summary。摘要含 phase/status/issue_count/next，完整回执保存任务目录并提供读取入口；摘要不代表已看图。

## 验证与交付边界

维护 SKILL.md、AGENTS.md、阶段/入口/工作流协议、架构与相关说明，运行 sync_skill_references.py 及 --check。旧默认测试显式请求 sparse，新增 Agent 默认与各公开入口共同约束测试。Linux 运行完整带 Mido 回归；CI 增加 Windows 原生重点套件与自包含 Skill 合成重放。

用户负责真实来源与跨宿主验收。实施方负责针对性测试、完整回归、静态检查、引用同步和可执行验收说明。没有用户真实回执或远端 CI 结果时保留待验，不以合成测试、历史重放或声明冒充实际视觉验收。未授权远端写入、共享安装更新或认证/宿主配置修改。
