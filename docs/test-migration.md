# 本轮转换算法回退的测试保留

2026-10-28，正式转换恢复到已部署 `2e1ce36`。`test_public_contracts.py` 和 `test_script_conversion.py` 中原基线的全部转换断言恢复，最近的 Windows 平台限定、HTTP 输入覆盖及两项 guardian 清理测试继续保留。日志、缓存、维护、队列容错、发行工具测试不回退。

撤回能力专属的三个测试模块及两个混合模块的完整回退前副本保存在提交 `4d75de5` 的 `experiments/issue88-withdrawn/tests/`，没有删除实验断言。原源码也留存于相邻 `src/`，准确实验版本为 `f4ccc81`。这些副本不参与正式 unittest 发现，不得据此宣称当前线上仍支持主曲选择、原生翻页或遮挡恢复。历史测试应在该版本的独立 checkout 执行。

# 旧测试到脚本产品的迁移记录

2026-10-25 撤回 YouTube 功能时，随其移除的 `test_youtube_input.py`、`youtube_fixture.py` 和公开入口成功发布测试只针对撤回的能力。B站获取、来源完整性、网络边界、受限进程和排版测试继续保留；新公开入口测试验证 watch/youtu.be/Shorts 在 Python、CLI、HTTP 均先于获取被拒绝且不创建输出。既有 `score_fixtures.py` 的 B站原生时长断言恢复，未删除仍适用的 B站保护要求。

2026-10-23 的并行修复保留累计 600 秒解码与公开入口总期限，移除单次额外 60 秒期限。新增 `test_contended_decoder_can_use_remaining_cumulative_budget` 以加速定时器和真实合成子进程复现旧限制，不把虚拟时间当作实测。`test_total_deadline_still_stops_continuous_decoder_in_each_entry` 在 Python、CLI、HTTP/worker 三入口实际进入阻塞解码，再由两秒总期限停止进程并核验清理。原累计预算与失败保护断言保留。

本文是 #73 当时从 Skill 收口到程序产品的历史记录。[ADR 0007](adr/0007-independent-skill-and-website.md) 已恢复同仓库中的独立 Skill 和 `tests/skill/`。下表“专属退役”只说明当时未移入程序包的行为，不表示现在从 Skill 删除；当前分开运行的命令见 [Skill 验证](skill-verification.md)和[程序验证](verification.md)。

本文逐项保留旧版 217 个测试 ID，并记录 #73 的实际去向。它用于审阅删除测试时保留了哪些契约，不是测试通过回执。独立安装记录已交付，见 `I-73`，最终提交与 tree 绑定见外部 `product73-packaging/final-binding.json`。两项累计解码预算由真实进程耗时补证，见 `B-73`。

## 范围与证据

旧清单绑定提交 `7a8c1af5e24031f2f9824527f589240c58dcb7f3`，来自实施前的逐项迁移矩阵。旧源码可通过 Git history 查看，不恢复旧 Skill、手工重建、模型调用、MIDI 或批准入口。

本页于 2026-10-22 根据 `codex/issue-73-product` 工作树编写，基线 HEAD 为 `9b85b0f4e3c5a7b0fabc48ed76dfdbb4a9b0597d`。最终源码身份由外部 `product73-packaging/final-binding.json` 记录。表中所有目标 unittest ID 都经 AST 静态存在性检查；本次文档工作没有执行测试。实际运行结果与提交绑定由最终验证记录提供。

- 原 ID 保留表示同名方法继续存在，导入或夹具可已迁包。旧 CLI/workflow 分支退出时，保留的是当前 acquire 或脚本入口适用分支。
- 语义迁移表示旧操作退出，表内目标验证新产品仍需保留的后果。多个旧 ID 可以对应同一目标；目标不存在时不得填入建议名称。
- 专属退役表示整项行为随旧产品退出。共享网络、来源、输出保护不能因为所在文件删除而退役。
- `S-73` 是当前静态产品证据。`pyproject.toml` 声明 Python `>=3.12`、基础依赖、web extra 和三个入口；`.github/workflows/offline.yml` 的三个 job 使用 Python 3.12；`src/drum_score/web.py` 使用固定 attachment 文件名。静态核对不代表安装或远端 CI 已通过。
- `I-73` 是下文的独立安装记录。无缓存包、当前源码与两个安装环境的字节已核对，最终提交绑定见外部 `product73-packaging/final-binding.json`。源码 `sys.path` 测试及旧 #72 安装回执不能替代。
- `B-73` 保留同一 reader 的真实累计解码后果。`test_media_boundary.MediaBoundaryTests.test_failed_decoders_charge_real_elapsed_and_exhaust_remaining_budget` 仅通过 PATH 替换外部 FFmpeg：从明确的近预算状态开始，首次解码进程实际等待 0.15 秒后失败；生产单调时钟计费后，第二个计划等待 10 秒的进程在剩余额度内被停止，累计到耗尽；第三次不再启动进程。测试不手写新增耗时，检查实际启动 marker 和原来源、暂存保护，专项日志为 `/home/kenqia/issue69-context/budget73-real.log`。旧 `test_decode_failure_preserves_existing_output_and_charges_attempt_budget` 的手加 60 仍只说明受控失败保护文件，不作为实测。旧跨 stage/跨请求预算协议退出。

协议测试保留 DNS/TLS 固定、公共地址、代理、备份、完整时长与匿名边界。API 协议分支会替换 supervision，不能称作 spawn 端到端验证。真实 CLI/worker、信号和 guardian 测试另行覆盖进程后果。HTTP 只接受公开链接，不能宣称覆盖本地文件输入。

当前预览失败测试涵盖 Python/CLI 和独立 HTTP worker，实际工具失败后没有可下载的半成品。未知旧操作测试对适用三个 CLI 及 HTTP 请求比较真实文件清单和 SHA256。连续分页测试从实际 PDF 读取图像 placement、核对跨页比例，再逐条带比对原始像素。这些断言在迁移时保留。

## I-73 独立安装记录

证据目录为 `/home/kenqia/issue69-context/product73-packaging/`，仅在本机可用。构建脚本 `build.py` 从独立源码副本执行 `uv build --sdist --wheel --no-cache`，记录在 `build.log` 和 `identity.json`。wheel SHA256 为 `6d14ee43ce7860b8918b1c09197e1d390dc5422ba95e62d6000d428806edcc59`，sdist SHA256 为 `8e64caffb25a439d5050b26f52d64027c280638c2f0f18cb861d6ad54644e3b5`。

实施者交付的实际命令如下，两次调用均从仓库外 `/tmp` 启动，返回值为 0：

```sh
env -u PYTHONPATH /home/kenqia/issue73-base-venv/bin/python /home/kenqia/issue69-context/product73-packaging/smoke.py
env -u PYTHONPATH /home/kenqia/issue73-installed-venv/bin/python /home/kenqia/issue69-context/product73-packaging/smoke.py
```

`base-smoke-report.json` 与 `base-smoke-final.log` 记录基础安装的真实 `drum-score` 转换，一页 PDF 与全部预览存在，实际 PTS/time_base 字段保留，原输入 hash 不变，FastAPI 和 Uvicorn 均未安装。`web-smoke-report.json` 与 `web-smoke-final2.log` 记录 web extra 的同项 CLI 验证，以及真实 HTTP CLI、静态资源、独立 worker、分 P 及原输入 hash、全部 PDF/预览回读。为快速验证物理清理，实际保留期限缩为 2 秒；随后状态、PDF、预览均为 410，受管结果被物理删除。这不代表生产 24 小时已经实际等待。

两个 `uv pip check` 返回值均为 0。`base-pip-check.log` 与 `web-pip-check.log` 分别记录 Python 3.12.12 的 7 个和 21 个依赖兼容。基础解释器为 `/home/kenqia/issue73-base-venv/bin/python`，web 解释器为 `/home/kenqia/issue73-installed-venv/bin/python`。

编写者独立读取包和安装文件，核对 `identity.json` 所列 20 个文件与当前源码、wheel、sdist、基础安装和 web 安装逐字节相同，包含四个迁入模块与三份静态资源。核对包 hash 与记录相同，没有重跑 smoke。`smoke.py` 读取仓库源码只为生成合成图像及取得窄网络替身；产品从 site-packages 导入。独立 worker 的 `PYTHONPATH` 仅加入这份临时网络替身，不包含 `src`。

第一次 `web-smoke-final.log` 在测试脚本要求 HTTP 进程必须返回 0 时失败。后续脚本明确接受主动 SIGTERM 的 0 或 -15，完整重跑成功，报告实际为 -15。失败记录保留，不称作新的产品修复。

此记录绑定上述包 hash 和本次字节核对的源码。最终交付提交 hash 与 tree 由外部 `product73-packaging/final-binding.json` 绑定，不在仓库内自引用未来提交。

## test_acquisition_lifecycle.AcquisitionLifecycleTests

| 旧测试 ID | 实际处理 | 保留语义或退役原因 | 当前测试或证据 |
| --- | --- | --- | --- |
| `test_acquisition_lifecycle.AcquisitionLifecycleTests.test_dns_timeout_stops_real_worker_and_leaves_only_retryable_diagnosis` | 原 ID 保留 | 真实DNS停滞进程被总期限停止，无来源/结果发布；诊断留存按新规则 | `test_acquisition_lifecycle.AcquisitionLifecycleTests.test_dns_timeout_stops_real_worker_and_leaves_only_retryable_diagnosis` |
| `test_acquisition_lifecycle.AcquisitionLifecycleTests.test_sigterm_stops_worker_and_returns_sanitized_retryable_failure` | 原 ID 保留 | 实际SIGTERM使下载树退出、脱敏回执及暂存清理 | `test_acquisition_lifecycle.AcquisitionLifecycleTests.test_sigterm_stops_worker_and_returns_sanitized_retryable_failure` |
| `test_acquisition_lifecycle.AcquisitionLifecycleTests.test_connections_download_retries_and_process_exit_share_deadline` | 原 ID 保留 | 提取、连接、下载、API回退、退出等待共用总期限 | `test_acquisition_lifecycle.AcquisitionLifecycleTests.test_connections_download_retries_and_process_exit_share_deadline` |
| `test_acquisition_lifecycle.AcquisitionLifecycleTests.test_probe_subprocess_is_stopped_by_overall_deadline` | 原 ID 保留 | 真实探测子进程纳入整体期限，不仅父进程返回失败 | `test_acquisition_lifecycle.AcquisitionLifecycleTests.test_probe_subprocess_is_stopped_by_overall_deadline` |
| `test_acquisition_lifecycle.AcquisitionLifecycleTests.test_killed_cli_never_leaves_partial_in_final_directory` | 原 ID 保留 | 实际CLI SIGKILL后无活动子树/最终半成品；guardian清理受管暂存 | `test_acquisition_lifecycle.AcquisitionLifecycleTests.test_killed_cli_never_leaves_partial_in_final_directory` |
| `test_acquisition_lifecycle.AcquisitionLifecycleTests.test_destination_copy_is_inside_deadline_and_cleans_its_staging` | 原 ID 保留 | 最终来源复制在同一期限内，阶段同步后超时清理暂存 | `test_acquisition_lifecycle.AcquisitionLifecycleTests.test_destination_copy_is_inside_deadline_and_cleans_its_staging` |

## test_agent_source.AgentSourceTests

| 旧测试 ID | 实际处理 | 保留语义或退役原因 | 当前测试或证据 |
| --- | --- | --- | --- |
| `test_agent_source.AgentSourceTests.test_stage_builds_longshot_without_claiming_overall_agent_approval` | 语义迁移 | 旧 stage退出；自动complete不生成视觉批准、reliable=false且附实际限制 | `test_public_contracts.ScriptPublicContracts.test_remote_script_matrix_preserves_source_pages_and_honest_completion` |
| `test_agent_source.AgentSourceTests.test_all_assembly_entries_require_present_but_accept_one_concrete_review` | 专属退役 | Agent实际看图/手动来源审阅、批准或宿主生成恢复功能退出，不迁移其批准协议。 | 无，旧专属功能退出。 |
| `test_agent_source.AgentSourceTests.test_unresolved_actual_source_problem_blocks_generation_until_reconfirmed` | 语义迁移 | 人工问题单退出；程序已识别来源缺段/损坏不得成功 | `test_script_conversion.ScriptConversion.test_detected_page_flip_does_not_silently_publish_only_first_page`；`test_script_conversion.ScriptConversion.test_native_motion_between_identical_samples_never_publishes_shortened_score` |
| `test_agent_source.AgentSourceTests.test_manual_path_exports_vector_without_fake_calls_and_reviews_current_revision` | 专属退役 | Agent实际看图/手动来源审阅、批准或宿主生成恢复功能退出，不迁移其批准协议。 | 无，旧专属功能退出。 |
| `test_agent_source.AgentSourceTests.test_local_replacement_and_return_preserve_unknown_call_and_unaffected_group` | 专属退役 | Agent实际看图/手动来源审阅、批准或宿主生成恢复功能退出，不迁移其批准协议。 | 无，旧专属功能退出。 |
| `test_agent_source.AgentSourceTests.test_crop_revision_requires_explicit_review_and_keeps_last_valid_state_on_error` | 语义迁移 | 人工crop/批准退出；错误不能撤销或覆盖已有有效产物 | `test_public_contracts.ScriptPublicContracts.test_script_entries_reject_existing_paths_and_invalid_source`；`test_script_conversion.ScriptConversion.test_changed_source_is_rejected_without_publishing_or_touching_other_results` |
| `test_agent_source.AgentSourceTests.test_partial_review_does_not_carry_approval_to_changed_selection` | 专属退役 | Agent实际看图/手动来源审阅、批准或宿主生成恢复功能退出，不迁移其批准协议。 | 无，旧专属功能退出。 |
| `test_agent_source.AgentSourceTests.test_source_approval_does_not_override_cut_stem_or_changed_review` | 语义迁移 | 旧source批准退出；任意完成字段不能绕过实际已知无效来源 | `test_script_conversion.ScriptConversion.test_detected_page_flip_does_not_silently_publish_only_first_page`；`test_public_contracts.ScriptPublicContracts.test_script_entries_publish_all_pages_or_no_result_for_black_input`。仅迁移新产品已识别的不可用来源拒绝，不声称识别任意断杆。 |
| `test_agent_source.AgentSourceTests.test_summary_preserves_complete_default_receipt_in_task_file` | 语义迁移 | 旧任务回执退出；manifest/返回值包含完整结果与有序全页 | `test_public_contracts.ScriptPublicContracts.test_remote_script_matrix_preserves_source_pages_and_honest_completion` |

## test_api_acquisition.APIAcquisitionTests

| 旧测试 ID | 实际处理 | 保留语义或退役原因 | 当前测试或证据 |
| --- | --- | --- | --- |
| `test_api_acquisition.APIAcquisitionTests.test_proxy_refusal_recovers_public_api_at_every_entry` | 原 ID 保留 | 仅已批准的代理CONNECT403恢复公共API；各最终入口一致 | `test_api_acquisition.APIAcquisitionTests.test_proxy_refusal_recovers_public_api_at_every_entry` |
| `test_api_acquisition.APIAcquisitionTests.test_api_unsafe_primary_uses_official_backup_at_every_entry` | 原 ID 保留 | API不安全主URL只能回退受校验同流官方备份 | `test_api_acquisition.APIAcquisitionTests.test_api_unsafe_primary_uses_official_backup_at_every_entry` |
| `test_api_acquisition.APIAcquisitionTests.test_webpage_412_recovers_without_requiring_proxy_refusal` | 原 ID 保留 | 网页412通用匿名API恢复，无需真实代理或登录 | `test_api_acquisition.APIAcquisitionTests.test_webpage_412_recovers_without_requiring_proxy_refusal` |
| `test_api_acquisition.APIAcquisitionTests.test_api_recovery_rejects_private_media_dns` | 原 ID 保留 | API恢复仍拒绝私有媒体DNS | `test_api_acquisition.APIAcquisitionTests.test_api_recovery_rejects_private_media_dns` |
| `test_api_acquisition.APIAcquisitionTests.test_other_refusals_do_not_trigger_direct_api` | 原 ID 保留 | 未批准拒绝类型不擅自改变网络路由 | `test_api_acquisition.APIAcquisitionTests.test_other_refusals_do_not_trigger_direct_api` |
| `test_api_acquisition.APIAcquisitionTests.test_wrong_or_ambiguous_page_never_downloads_media` | 原 ID 保留 | BV/分P/cid明确绑定，错误或歧义不下载 | `test_api_acquisition.APIAcquisitionTests.test_wrong_or_ambiguous_page_never_downloads_media` |
| `test_api_acquisition.APIAcquisitionTests.test_restricted_or_preview_api_response_never_downloads_media` | 原 ID 保留 | 受限/试看响应不得称完整来源 | `test_api_acquisition.APIAcquisitionTests.test_restricted_or_preview_api_response_never_downloads_media` |
| `test_api_acquisition.APIAcquisitionTests.test_actual_media_duration_must_match_the_api_not_just_its_dimensions` | 原 ID 保留 | 实际完整时长与API绑定，尺寸正确不等于完整曲长 | `test_api_acquisition.APIAcquisitionTests.test_actual_media_duration_must_match_the_api_not_just_its_dimensions` |
| `test_api_acquisition.APIAcquisitionTests.test_script_conversion_entries_share_real_downloader_boundary` | 原 ID 保留 | 协议层复用下载器；旧 CLI/workflow 枚举退出，当前 Python/CLI 分支保留；HTTP 边界另见远端公开共同矩阵 | `test_api_acquisition.APIAcquisitionTests.test_script_conversion_entries_share_real_downloader_boundary` |

## test_ci_replay.CIReplayTests

| 旧测试 ID | 实际处理 | 保留语义或退役原因 | 当前测试或证据 |
| --- | --- | --- | --- |
| `test_ci_replay.CIReplayTests.test_offline_replay_produces_bounded_sanitized_evidence` | 原 ID 保留 | 纯程序合成端到端证据有界且脱敏；Agent批准回放退出 | `test_ci_replay.CIReplayTests.test_offline_replay_produces_bounded_sanitized_evidence` |
| `test_ci_replay.CIReplayTests.test_failure_evidence_excludes_subprocess_paths_and_logs` | 原 ID 保留 | 失败报告不上传原始子进程日志、私有路径、签名地址 | `test_ci_replay.CIReplayTests.test_failure_evidence_excludes_subprocess_paths_and_logs` |

## test_ci_shards.CiShardTests

| 旧测试 ID | 实际处理 | 保留语义或退役原因 | 当前测试或证据 |
| --- | --- | --- | --- |
| `test_ci_shards.CiShardTests.test_shard_lists_partition_discovery_and_reject_invalid_index` | 原 ID 保留 | 分片并集完整、交集为空、非法索引拒绝 | `test_ci_shards.CiShardTests.test_shard_lists_partition_discovery_and_reject_invalid_index` |
| `test_ci_shards.CiShardTests.test_import_error_fails_every_shard_including_listing` | 原 ID 保留 | 任意discovery导入错误使各分片失败，不因未选中而掩盖 | `test_ci_shards.CiShardTests.test_import_error_fails_every_shard_including_listing` |
| `test_ci_shards.CiShardTests.test_selected_failure_returns_nonzero_and_empty_shard_is_rejected` | 原 ID 保留 | 实际失败退出非零，空分片不报虚假成功 | `test_ci_shards.CiShardTests.test_selected_failure_returns_nonzero_and_empty_shard_is_rejected` |

## test_ci_windows_tools.WindowsToolBootstrap

| 旧测试 ID | 实际处理 | 保留语义或退役原因 | 当前测试或证据 |
| --- | --- | --- | --- |
| `test_ci_windows_tools.WindowsToolBootstrap.test_existing_executables_need_no_install` | 原 ID 保留 | 已有工具不重复安装，不改无关环境 | `test_ci_windows_tools.WindowsToolBootstrap.test_existing_executables_need_no_install` |
| `test_ci_windows_tools.WindowsToolBootstrap.test_zero_exit_without_tools_retries_then_fails` | 原 ID 保留 | 安装命令0退出不等于工具就绪，实际检查并有界失败 | `test_ci_windows_tools.WindowsToolBootstrap.test_zero_exit_without_tools_retries_then_fails` |
| `test_ci_windows_tools.WindowsToolBootstrap.test_transient_feed_failure_recovers_and_checks_next_package` | 原 ID 保留 | 临时包源故障有界重试，各必要包均验证 | `test_ci_windows_tools.WindowsToolBootstrap.test_transient_feed_failure_recovers_and_checks_next_package` |
| `test_ci_windows_tools.WindowsToolBootstrap.test_timeout_retries_with_a_bound` | 原 ID 保留 | 安装超时及重试有界，不无限等待 | `test_ci_windows_tools.WindowsToolBootstrap.test_timeout_retries_with_a_bound` |
| `test_ci_windows_tools.WindowsToolBootstrap.test_probe_requires_every_executable_and_successful_exit` | 原 ID 保留 | FFmpeg/ffprobe/Poppler各工具存在且真实执行成功 | `test_ci_windows_tools.WindowsToolBootstrap.test_probe_requires_every_executable_and_successful_exit` |
| `test_ci_windows_tools.WindowsToolBootstrap.test_probe_rejects_missing_or_hanging_executable` | 原 ID 保留 | 缺失或挂起工具明确拒绝，不能继续验收 | `test_ci_windows_tools.WindowsToolBootstrap.test_probe_rejects_missing_or_hanging_executable` |

## test_compact_layout.CompactLayout

| 旧测试 ID | 实际处理 | 保留语义或退役原因 | 当前测试或证据 |
| --- | --- | --- | --- |
| `test_compact_layout.CompactLayout.test_reduces_three_pages_to_two_at_largest_common_scale` | 语义迁移 | 保留统一比例和完整覆盖；旧10%紧凑策略不强制兼容 | `test_script_conversion.ScriptConversion.test_page_balancing_moves_whole_groups_to_sparse_final_page`；`test_script_conversion.ScriptConversion.test_continuous_pages_preserve_gray_spacing_detached_marks_and_pale_short_ending` |
| `test_compact_layout.CompactLayout.test_preserves_original_size_without_page_savings_or_beyond_ten_percent` | 专属退役 | 旧可选10%缩小和原尺寸决策不再是新产品契约 | 无，旧专属功能退出。 |
| `test_compact_layout.CompactLayout.test_small_or_unknown_staff_geometry_keeps_original_size` | 语义迁移 | 保留可读性与不猜未知几何，不迁移旧尺寸策略 | `test_script_conversion.ScriptConversion.test_no_safe_gap_preserves_tall_group_without_hard_cut`；`test_public_contracts.ScriptPublicContracts.test_script_entries_publish_all_pages_or_no_result_for_black_input` |
| `test_compact_layout.CompactLayout.test_ink_or_joined_systems_prevent_unsafe_page_savings` | 语义迁移 | 相关记号/墨迹跨行时整组保留，拒绝以省页硬切 | `test_script_conversion.ScriptConversion.test_no_safe_gap_preserves_tall_group_without_hard_cut` |
| `test_compact_layout.CompactLayout.test_manual_breaks_keep_original_scale_and_height_refusal` | 专属退役 | 人工切口接口退出；新核心超高组整体缩小契约由现有测试保留 | 无，旧专属功能退出。 |
| `test_compact_layout.CompactLayout.test_balancing_finds_feasible_global_partition` | 语义迁移 | 均衡连续条带，保持整体行组顺序/覆盖/最少可行页数 | `test_script_conversion.ScriptConversion.test_page_balancing_moves_whole_groups_to_sparse_final_page` |

## test_cross_host.SeekCompatibility

| 旧测试 ID | 实际处理 | 保留语义或退役原因 | 当前测试或证据 |
| --- | --- | --- | --- |
| `test_cross_host.SeekCompatibility.test_capability_matrix_and_bounded_failure_fallback` | 原 ID 保留 | FFmpeg新旧同步参数能力探测缓存及5秒失败边界 | `test_cross_host.SeekCompatibility.test_capability_matrix_and_bounded_failure_fallback` |
| `test_cross_host.SeekCompatibility.test_native_read_uses_selected_frame_sync_options` | 原 ID 保留 | 实际VideoReader使用所选同步参数且保留实际PTS | `test_cross_host.SeekCompatibility.test_native_read_uses_selected_frame_sync_options` |

## test_cross_host.HostDiscovery

| 旧测试 ID | 实际处理 | 保留语义或退役原因 | 当前测试或证据 |
| --- | --- | --- | --- |
| `test_cross_host.HostDiscovery.test_unreadable_unrelated_skill_warns_and_valid_target_is_discovered` | 专属退役 | Skill发现功能退出，不扫描宿主Skill目录 | 无，旧专属功能退出。 |
| `test_cross_host.HostDiscovery.test_explicit_function_probe_uses_real_synthetic_pts` | 语义迁移 | 保留真实合成解码/PTS测试；host_check.decode_probe入口退出 | `test_media_boundary.MediaBoundaryTests.test_installed_reader_decodes_real_synthetic_pts`。源码合成解码，名称中的 installed 不代表独立安装；安装另见 I-73。 |

## test_delivery_layout.DeliveryLayoutTests

| 旧测试 ID | 实际处理 | 保留语义或退役原因 | 当前测试或证据 |
| --- | --- | --- | --- |
| `test_delivery_layout.DeliveryLayoutTests.test_filename_is_portable_and_cannot_escape_output` | 专属退役，条件未触发 | 当前固定score.pdf时标题命名功能退出；若HTTP实际暴露标题文件名则覆盖保留名/穿越/控制字符/字节上限/CRLF | 固定磁盘名 `score.pdf` 和 HTTP attachment 名 `drum-score.pdf`，没有标题命名输入。静态证据见 S-73；不恢复标题接口。 |

## test_host_check.HostCheckTests

| 旧测试 ID | 实际处理 | 保留语义或退役原因 | 当前测试或证据 |
| --- | --- | --- | --- |
| `test_host_check.HostCheckTests.test_explicit_root_reports_duplicate_entries_and_unknown_capabilities` | 专属退役 | 宿主Skill发现和能力报告退出 | 无，旧专属功能退出。 |
| `test_host_check.HostCheckTests.test_runtime_version_policy_at_both_host_check_entries` | 语义迁移，安装实证 | host_check退出；最终包Requires-Python与实际安装兼容性保留 | S-73；I-73，提交绑定见 `product73-packaging/final-binding.json`。旧 host_check 入口退出；Python 元数据与真实安装兼容性分开核对。 |
| `test_host_check.HostCheckTests.test_every_ci_job_uses_the_supported_python_minor` | 语义迁移，静态配置 | CI解释器与真实受支持Python范围一致 | S-73。三个 CI job 均为 Python 3.12；不宣称远端 CI 已执行或所有 >=3.12 版本均实测。 |

## test_link_input.LinkInputTests

| 旧测试 ID | 实际处理 | 保留语义或退役原因 | 当前测试或证据 |
| --- | --- | --- | --- |
| `test_link_input.LinkInputTests.test_dash_only_link_uses_native_video_track_and_records_anonymous_backend` | 原 ID 保留 | 保留公开视频视频轨、分P与匿名后端来源，移除prepare/record字段 | `test_link_input.LinkInputTests.test_dash_only_link_uses_native_video_track_and_records_anonymous_backend` |
| `test_link_input.LinkInputTests.test_highest_native_resolution_video_only_wins_over_muxed_or_audio` | 原 ID 保留 | 优先原生最高分辨率视频轨，不能被音轨或muxed低清替代 | `test_link_input.LinkInputTests.test_highest_native_resolution_video_only_wins_over_muxed_or_audio` |
| `test_link_input.LinkInputTests.test_no_separate_video_records_single_file_fallback` | 原 ID 保留 | 无独立视频轨时允许合法单文件回退并如实记录 | `test_link_input.LinkInputTests.test_no_separate_video_records_single_file_fallback` |
| `test_link_input.LinkInputTests.test_metadata_cannot_claim_higher_resolution_than_download` | 原 ID 保留 | 实测媒体尺寸必须达到声明，不能只信元数据 | `test_link_input.LinkInputTests.test_metadata_cannot_claim_higher_resolution_than_download` |
| `test_link_input.LinkInputTests.test_official_backup_can_recover_http_failure_without_leaking_signature` | 原 ID 保留 | 同流官方备份恢复，签名URL/原始异常不泄漏 | `test_link_input.LinkInputTests.test_official_backup_can_recover_http_failure_without_leaking_signature` |
| `test_link_input.LinkInputTests.test_media_412_is_sanitized_and_leaves_no_download_in_output` | 原 ID 保留 | 媒体412公开错误脱敏，失败不发布下载或PDF | `test_link_input.LinkInputTests.test_media_412_is_sanitized_and_leaves_no_download_in_output` |
| `test_link_input.LinkInputTests.test_private_dns_and_unsafe_media_targets_are_rejected_before_transport` | 原 ID 保留 | 公共地址、媒体域/端口约束在连接前执行 | `test_link_input.LinkInputTests.test_private_dns_and_unsafe_media_targets_are_rejected_before_transport` |
| `test_link_input.LinkInputTests.test_https_redirect_to_private_dns_is_rejected` | 原 ID 保留 | 每次重定向重新检查公共DNS，拒绝SSRF | `test_link_input.LinkInputTests.test_https_redirect_to_private_dns_is_rejected` |
| `test_link_input.LinkInputTests.test_invalid_initial_url_never_invokes_backend` | 原 ID 保留 | 非法初始BV/协议/分P不启动下载 | `test_link_input.LinkInputTests.test_invalid_initial_url_never_invokes_backend` |
| `test_link_input.LinkInputTests.test_existing_user_partial_and_results_are_preserved` | 原 ID 保留 | 已有用户目录与.partial文件不覆盖，不沿用旧目录结构 | `test_link_input.LinkInputTests.test_existing_user_partial_and_results_are_preserved` |
| `test_link_input.LinkInputTests.test_acquisition_failure_can_retry_same_directory_without_overwriting_user_files` | 原 ID 保留 | 保留失败后用户文件；同目录prepare重试退出，HTTP显式重试新attempt | `test_link_input.LinkInputTests.test_acquisition_failure_can_retry_same_directory_without_overwriting_user_files` |
| `test_link_input.LinkInputTests.test_failure_diagnosis_with_unknown_files_cannot_retry` | 原 ID 保留 | 未知文件不被重试接管或删除；旧诊断目录恢复协议退出 | `test_link_input.LinkInputTests.test_failure_diagnosis_with_unknown_files_cannot_retry` |
| `test_link_input.LinkInputTests.test_probe_failure_can_retry_the_same_directory` | 原 ID 保留 | 探测失败无成功产物，重试新attempt可成功；旧目录复用退出 | `test_link_input.LinkInputTests.test_probe_failure_can_retry_the_same_directory` |
| `test_link_input.LinkInputTests.test_cross_filesystem_publication_uses_exclusive_complete_video` | 原 ID 保留 | 跨FS来源复制也遵守期限、独占完整发布及不覆盖 | `test_link_input.LinkInputTests.test_cross_filesystem_publication_uses_exclusive_complete_video` |
| `test_link_input.LinkInputTests.test_config_cookie_netrc_and_plugin_sentinels_are_not_read` | 原 ID 保留 | 仅合成sentinel验证不读取用户配置/Cookie/netrc/plugin，禁止真实凭据 | `test_link_input.LinkInputTests.test_config_cookie_netrc_and_plugin_sentinels_are_not_read` |
| `test_link_input.LinkInputTests.test_actual_connection_pins_public_dns_and_keeps_tls_hostname` | 原 ID 保留 | 固定实际连接到已验证公共IP，同时TLS主机名仍校验原域 | `test_link_input.LinkInputTests.test_actual_connection_pins_public_dns_and_keeps_tls_hostname` |
| `test_link_input.LinkInputTests.test_environment_proxy_tunnels_to_pinned_origin_without_forwarding_credentials` | 原 ID 保留 | 代理CONNECT保持公共IP约束，代理凭据不转发到源站 | `test_link_input.LinkInputTests.test_environment_proxy_tunnels_to_pinned_origin_without_forwarding_credentials` |
| `test_link_input.LinkInputTests.test_pinned_connect_host_handles_ipv6_retry_and_restores_headers` | 原 ID 保留 | 合法IPv6/地址重试、TLS原域及临时头恢复 | `test_link_input.LinkInputTests.test_pinned_connect_host_handles_ipv6_retry_and_restores_headers` |
| `test_link_input.LinkInputTests.test_wrong_page_and_undecodable_video_stop_without_publication` | 原 ID 保留 | 错分P/不可解码媒体明确失败且不发布 | `test_link_input.LinkInputTests.test_wrong_page_and_undecodable_video_stop_without_publication` |
| `test_link_input.LinkInputTests.test_redirects_reject_http_and_stop_after_five_hops` | 原 ID 保留 | 拒绝HTTPS降级并保留有界重定向 | `test_link_input.LinkInputTests.test_redirects_reject_http_and_stop_after_five_hops` |
| `test_link_input.LinkInputTests.test_extractor_can_read_metadata_through_real_bounded_transport` | 原 ID 保留 | 保留真实HTTP解析与有界transport协议路径 | `test_link_input.LinkInputTests.test_extractor_can_read_metadata_through_real_bounded_transport` |
| `test_link_input.LinkInputTests.test_real_webpage_path_keeps_default_headers_and_tries_next_public_address` | 原 ID 保留 | 真实网页提取保留必要默认头与公共地址回退 | `test_link_input.LinkInputTests.test_real_webpage_path_keeps_default_headers_and_tries_next_public_address` |

## test_longshot_cli.LongshotCLI

| 旧测试 ID | 实际处理 | 保留语义或退役原因 | 当前测试或证据 |
| --- | --- | --- | --- |
| `test_longshot_cli.LongshotCLI.test_stage_stitches_all_systems_without_manual_selection_or_pixel_cleanup` | 语义迁移 | 整曲所有系统、默认不猜隐藏记号、不按颜色清理 | `test_script_conversion.ScriptConversion.test_scrolling_preserves_every_position_and_full_endpoints`；`test_script_conversion.ScriptConversion.test_continuous_pages_preserve_gray_spacing_detached_marks_and_pale_short_ending` |
| `test_longshot_cli.LongshotCLI.test_one_overall_review_produces_vector_pdf_without_per_row_receipts` | 专属退役 | 整体Agent批准和矢量产物入口退出 | 无，旧专属功能退出。 |
| `test_longshot_cli.LongshotCLI.test_new_task_exports_original_rows_without_generation` | 语义迁移 | 自动原图PDF/全部预览与不调用模型保留；旧 stage/批准退出 | `test_script_conversion.ScriptConversion.test_static_video_produces_complete_a4_pages_and_actual_source_records`；`test_public_contracts.ScriptPublicContracts.test_remote_script_matrix_preserves_source_pages_and_honest_completion`。固定原图自动转换，模型入口及依赖退出见 S-73；不保留旧批准。 |
| `test_longshot_cli.LongshotCLI.test_rendered_continuous_page_preserves_gray_background_and_detached_marks` | 语义迁移 | 连续条带保留灰底、原行距和分离记号，验证PDF实际嵌入像素 | `test_script_conversion.ScriptConversion.test_continuous_pages_preserve_gray_spacing_detached_marks_and_pale_short_ending` |
| `test_longshot_cli.LongshotCLI.test_explicit_page_breaks_change_only_pages_and_legacy_output_is_upgraded` | 专属退役 | 人工page_breaks和旧输出升级退出；通用分页完整性另迁移 | 无，旧专属功能退出。 |
| `test_longshot_cli.LongshotCLI.test_explicit_vector_route_and_return_to_original_preserve_prior_outputs` | 语义迁移 | 旧路线切换退出；已存在用户产物不覆盖仍保留 | `test_public_contracts.ScriptPublicContracts.test_script_entries_reject_existing_paths_and_invalid_source` |
| `test_longshot_cli.LongshotCLI.test_local_watermark_cleanup_preserves_original_and_pixels_outside_selection` | 专属退役 | 人工矩形去水印入口退出；默认原像素保守保留由新核心测试覆盖 | 无，旧专属功能退出。 |
| `test_longshot_cli.LongshotCLI.test_local_source_repair_retains_frame_provenance_and_requires_new_review` | 语义迁移 | 原生来源PTS/hash与派生区分保留；人工修补/新批准退出 | `test_media_boundary.MediaBoundaryTests.test_url_and_local_use_same_original_and_native_capture`；`test_script_conversion.ScriptConversion.test_native_tail_pts_regression_keeps_decoder_order_and_real_timestamps`；`test_web_worker.WebsiteWorker.test_delivery_prunes_native_images_and_records_honest_provenance` |
| `test_longshot_cli.LongshotCLI.test_generation_resumes_one_call_and_auto_cuts_accepted_image_after_one_correction` | 专属退役 | 模型调用/修正预算/生成图切分退出 | 无，旧专属功能退出。 |
| `test_longshot_cli.LongshotCLI.test_continuous_scrolling_keeps_intermediate_systems` | 语义迁移 | 连续上移保留首尾和中间系统，复用scrolling_video纯夹具 | `test_script_conversion.ScriptConversion.test_scrolling_preserves_every_position_and_full_endpoints` |
| `test_longshot_cli.LongshotCLI.test_blank_outro_does_not_erase_the_final_music_system` | 语义迁移 | 空白片尾仍留真实来源时间，但不能擦除最后系统 | `test_script_conversion.ScriptConversion.test_blank_outro_preserves_last_music_system_and_actual_source_tail` |
| `test_longshot_cli.LongshotCLI.test_vector_fallback_preserves_pale_short_ending_staff` | 语义迁移 | 矢量退出；浅色/短末行的可见音乐完整保留 | `test_script_conversion.ScriptConversion.test_continuous_pages_preserve_gray_spacing_detached_marks_and_pale_short_ending` |
| `test_longshot_cli.LongshotCLI.test_cleaned_image_can_separate_staffs_joined_by_playback_marker` | 语义迁移 | 不恢复人工清理；播放标记连接行组时仍完整等比、不硬切 | `test_script_conversion.ScriptConversion.test_no_safe_gap_preserves_tall_group_without_hard_cut` |

## test_media_backups.MediaBackupTests

| 旧测试 ID | 实际处理 | 保留语义或退役原因 | 当前测试或证据 |
| --- | --- | --- | --- |
| `test_media_backups.MediaBackupTests.test_unsafe_primary_and_first_backup_use_second_backup_on_both_routes` | 原 ID 保留 | 网页/API两路按安全约束选择后续官方备份 | `test_media_backups.MediaBackupTests.test_unsafe_primary_and_first_backup_use_second_backup_on_both_routes` |
| `test_media_backups.MediaBackupTests.test_all_unsafe_candidates_fail_without_transport_or_partial_file` | 原 ID 保留 | 全部候选不安全时不连接、不留半成品 | `test_media_backups.MediaBackupTests.test_all_unsafe_candidates_fail_without_transport_or_partial_file` |
| `test_media_backups.MediaBackupTests.test_private_dns_primary_is_rejected_before_trying_public_backup` | 原 ID 保留 | 每个候选独立公共DNS检查，不能先访问私网再回退 | `test_media_backups.MediaBackupTests.test_private_dns_primary_is_rejected_before_trying_public_backup` |
| `test_media_backups.MediaBackupTests.test_backup_still_obeys_size_resolution_and_duration_checks` | 原 ID 保留 | 备份仍须满足大小、原生尺寸及完整时长 | `test_media_backups.MediaBackupTests.test_backup_still_obeys_size_resolution_and_duration_checks` |
| `test_media_backups.MediaBackupTests.test_undecodable_backup_is_not_accepted` | 原 ID 保留 | 不可解码备份不能当成功来源 | `test_media_backups.MediaBackupTests.test_undecodable_backup_is_not_accepted` |

## test_media_boundary.MediaBoundaryTests

| 旧测试 ID | 实际处理 | 保留语义或退役原因 | 当前测试或证据 |
| --- | --- | --- | --- |
| `test_media_boundary.MediaBoundaryTests.test_failed_longshot_retry_keeps_decode_budget_and_previous_materials` | 语义迁移，实测预算 | 单次任务解码累计预算及已发布产物保持；旧跨 stage重拼预算退出 | `test_media_boundary.MediaBoundaryTests.test_decode_failure_preserves_existing_output_and_charges_attempt_budget`；`test_script_conversion.ScriptConversion.test_total_deadline_stops_child_decoder_and_cleans_owned_temporary_root`；`test_media_boundary.MediaBoundaryTests.test_failed_decoders_charge_real_elapsed_and_exhaust_remaining_budget`；B-73，真实失败耗时累计、剩余预算停止及耗尽不启动；手填 60 不作实测。 |
| `test_media_boundary.MediaBoundaryTests.test_url_and_local_use_same_original_and_native_capture` | 原 ID 保留 | URL与相同本地字节使用同一实际来源hash/PTS，不依赖旧capture接口 | `test_media_boundary.MediaBoundaryTests.test_url_and_local_use_same_original_and_native_capture` |
| `test_media_boundary.MediaBoundaryTests.test_oversized_media_does_not_publish_video_and_can_retry_locally` | 原 ID 保留 | 超额来源不发布；合法本地输入新任务可独立运行 | `test_media_boundary.MediaBoundaryTests.test_oversized_media_does_not_publish_video_and_can_retry_locally` |
| `test_media_boundary.MediaBoundaryTests.test_actual_pts_tail_and_temporary_cleanup` | 原 ID 保留 | 实际PTS/time_base、真实尾帧、scratch有界与关闭清理 | `test_media_boundary.MediaBoundaryTests.test_actual_pts_tail_and_temporary_cleanup` |

## test_native_cache_cli.NativeCacheCLI

| 旧测试 ID | 实际处理 | 保留语义或退役原因 | 当前测试或证据 |
| --- | --- | --- | --- |
| `test_native_cache_cli.NativeCacheCLI.test_resumed_navigation_promotes_native_without_another_decode` | 专属退役 | 旧导航原生缓存/缓存晋升与宿主调用预算恢复退出；新产品不提供旧任务缓存迁移。 | 无，旧专属功能退出。 |
| `test_native_cache_cli.NativeCacheCLI.test_eviction_keeps_promoted_evidence_and_missing_cache_is_redecoded` | 专属退役 | 旧导航原生缓存/缓存晋升与宿主调用预算恢复退出；新产品不提供旧任务缓存迁移。 | 无，旧专属功能退出。 |
| `test_native_cache_cli.NativeCacheCLI.test_changed_source_rejects_cache_resume` | 语义迁移 | 旧缓存恢复退出；来源变化不得复用错误hash或发布结果 | `test_script_conversion.ScriptConversion.test_changed_source_is_rejected_without_publishing_or_touching_other_results` |
| `test_native_cache_cli.NativeCacheCLI.test_uncertain_call_recovery_keeps_budget_and_returns_complete_materials` | 专属退役 | 旧导航原生缓存/缓存晋升与宿主调用预算恢复退出；新产品不提供旧任务缓存迁移。 | 无，旧专属功能退出。 |
| `test_native_cache_cli.NativeCacheCLI.test_evicted_or_missing_candidate_is_a_reported_miss_after_restart` | 专属退役 | 旧导航原生缓存/缓存晋升与宿主调用预算恢复退出；新产品不提供旧任务缓存迁移。 | 无，旧专属功能退出。 |
| `test_native_cache_cli.NativeCacheCLI.test_default_groups_cover_continuous_rows_independently_of_a4` | 语义迁移 | 生图组退出；整曲材料完整覆盖，不让A4页界决定丢行 | `test_script_conversion.ScriptConversion.test_scrolling_preserves_every_position_and_full_endpoints`；`test_script_conversion.ScriptConversion.test_continuous_pages_preserve_gray_spacing_detached_marks_and_pale_short_ending` |
| `test_native_cache_cli.NativeCacheCLI.test_default_grouping_limits_effective_small_symbol_resolution` | 专属退役 | 宿主生图分组的分辨率预算退出；不移植旧生成缩放约束 | 无，旧专属功能退出。 |

## test_new_entry.NewEntryTests

| 旧测试 ID | 实际处理 | 保留语义或退役原因 | 当前测试或证据 |
| --- | --- | --- | --- |
| `test_new_entry.NewEntryTests.test_default_prepares_current_task_and_resumes_without_midi` | 语义迁移 | 新主线不再prepare/resume；安装CLI只暴露当前PDF功能且无MIDI/模型入口 | `test_public_contracts.ScriptPublicContracts.test_public_cli_parsers_do_not_echo_invalid_arguments_or_private_payload`。旧操作拒绝有实际文件清单/hash断言；安装 CLI 的实际入口见 I-73，提交绑定见 `product73-packaging/final-binding.json`。 |
| `test_new_entry.NewEntryTests.test_old_task_and_unknown_operation_preserve_user_files` | 语义迁移 | 不迁移旧任务，未知操作不改用户文件 | `test_public_contracts.ScriptPublicContracts.test_public_cli_parsers_do_not_echo_invalid_arguments_or_private_payload` |
| `test_new_entry.NewEntryTests.test_public_requests_deliver_reviewed_vector_pdf` | 专属退役 | JSON批请求、矢量和审核交付退出 | 无，旧专属功能退出。 |
| `test_new_entry.NewEntryTests.test_malformed_request_does_not_expose_traceback_or_payload` | 语义迁移 | CLI/HTTP畸形输入不泄漏traceback、原始载荷、私有路径 | `test_public_contracts.ScriptPublicContracts.test_public_cli_parsers_do_not_echo_invalid_arguments_or_private_payload`；`test_web.WebsiteHTTP.test_body_limit_precedes_json_parser_for_regular_and_chunked_requests` |

## test_public_contracts.PublicContracts

| 旧测试 ID | 实际处理 | 保留语义或退役原因 | 当前测试或证据 |
| --- | --- | --- | --- |
| `test_public_contracts.PublicContracts.test_longshot_entries_share_overall_review_and_source_integrity_contracts` | 语义迁移 | 退役整体批准；保留损坏来源/来源映射不发布且不改已有结果 | `test_script_conversion.ScriptConversion.test_changed_source_is_rejected_without_publishing_or_touching_other_results`；`test_public_contracts.ScriptPublicContracts.test_script_entries_reject_existing_paths_and_invalid_source` |
| `test_public_contracts.PublicContracts.test_removed_routes_and_stage_modes_cannot_mutate_existing_task` | 语义迁移 | 旧操作列表退出；未知CLI/HTTP操作不能变更用户旧任务 | `test_public_contracts.ScriptPublicContracts.test_public_cli_parsers_do_not_echo_invalid_arguments_or_private_payload` |
| `test_public_contracts.PublicContracts.test_print_mutations_share_boundaries_and_source_integrity` | 语义迁移 | 手工打印变更退出；统一比例/完整分页与source不变继续约束各入口 | `test_script_conversion.ScriptConversion.test_continuous_pages_preserve_gray_spacing_detached_marks_and_pale_short_ending`；`test_public_contracts.ScriptPublicContracts.test_remote_script_matrix_preserves_source_pages_and_honest_completion`。手工打印修改入口退出；比例由核心 PDF 测试验证，公开入口矩阵核对原来源hash和当前全页。 |
| `test_public_contracts.PublicContracts.test_legacy_longshot_keeps_unknown_request_and_route_changes_wait_for_recovery` | 专属退役 | 旧未知模型调用与路线切换恢复退出 | 无，旧专属功能退出。 |
| `test_public_contracts.PublicContracts.test_explicit_redraw_entries_select_route_and_expose_unknown_calls` | 专属退役 | 显式重绘/未知调用入口退出 | 无，旧专属功能退出。 |
| `test_public_contracts.PublicContracts.test_manual_source_revision_preserves_explicit_vector_route` | 专属退役 | 人工来源版本和矢量选择退出 | 无，旧专属功能退出。 |
| `test_public_contracts.PublicContracts.test_explicit_vector_export_selects_route_instead_of_being_replaced_by_stage` | 专属退役 | 矢量导出/旧 stage路线选择退出 | 无，旧专属功能退出。 |
| `test_public_contracts.PublicContracts.test_windows_utf8_bom_request_uses_the_same_stage_contract` | 专属退役 | 旧UTF8-BOM请求文件协议退出；不因此新增网页BOM文件接口 | 无，旧专属功能退出。 |
| `test_public_contracts.PublicContracts.test_source_recovery_entries_refuse_corrupt_sources_without_mutation` | 语义迁移 | 旧恢复入口退出；来源hash变动/损坏不发布、不覆盖已有结果 | `test_script_conversion.ScriptConversion.test_changed_source_is_rejected_without_publishing_or_touching_other_results`；`test_public_contracts.ScriptPublicContracts.test_script_entries_reject_existing_paths_and_invalid_source` |
| `test_public_contracts.PublicContracts.test_manual_cut_stem_blocks_every_generation_entry_until_crop_is_repaired` | 语义迁移 | 人工裁框/生成门禁退出；已确认切断或不可用谱面不得假成功 | `test_script_conversion.ScriptConversion.test_detected_page_flip_does_not_silently_publish_only_first_page`；`test_public_contracts.ScriptPublicContracts.test_script_entries_publish_all_pages_or_no_result_for_black_input`。程序已识别的翻页/黑视频拒绝；不把它描述为逐符号切杆识别。 |
| `test_public_contracts.PublicContracts.test_manual_stem_endpoint_touching_boundary_is_reported` | 专属退役 | 人工裁框触边专属诊断退出；不把旧人工门禁移植成新颜色/边界启发式 | 无，旧专属功能退出。 |
| `test_public_contracts.PublicContracts.test_every_request_entry_keeps_all_groups_and_preserves_dispatch_state` | 语义迁移 | 生成dispatch退出；全曲所有系统不丢和顺序约束保留 | `test_script_conversion.ScriptConversion.test_scrolling_preserves_every_position_and_full_endpoints`；`test_script_conversion.ScriptConversion.test_repeated_music_with_small_measure_numbers_retains_fast_scroll_positions` |
| `test_public_contracts.PublicContracts.test_batch_rejects_duplicate_request_ids_and_wrong_input_hash` | 专属退役 | 模型batch请求与输入hash协议退出；HTTP attempt身份另建生命周期测试 | 无，旧专属功能退出。 |
| `test_public_contracts.PublicContracts.test_every_export_obeys_layout_and_every_review_binds_current_previews` | 语义迁移 | 终稿review token退出；只有当前完整产物和全部预览可公开 | `test_public_contracts.ScriptPublicContracts.test_remote_script_matrix_preserves_source_pages_and_honest_completion`；`test_web_worker.WebsiteWorker.test_preview_tool_failure_never_completes_or_serves_partial_result` |
| `test_public_contracts.PublicContracts.test_continuous_layout_entries_refuse_invalid_cuts_without_revoking_output` | 语义迁移 | 人工切口退出；失败不覆盖有效产物且保持整组分页 | `test_script_conversion.ScriptConversion.test_no_safe_gap_preserves_tall_group_without_hard_cut`；`test_public_contracts.ScriptPublicContracts.test_script_entries_reject_existing_paths_and_invalid_source` |
| `test_public_contracts.PublicContracts.test_direct_exports_share_layout_and_current_page_review_contracts` | 语义迁移 | Agent页审核退出；公开入口共用统一比例、A4与全部页 | `test_script_conversion.ScriptConversion.test_continuous_pages_preserve_gray_spacing_detached_marks_and_pale_short_ending`；`test_script_conversion.ScriptConversion.test_static_video_produces_complete_a4_pages_and_actual_source_records`；`test_public_contracts.ScriptPublicContracts.test_remote_script_matrix_preserves_source_pages_and_honest_completion` |
| `test_public_contracts.PublicContracts.test_direct_export_entries_compact_without_resampling_or_moving_detached_marks` | 语义迁移 | 连续原图像素/行距/分离记号关系，各入口同一打印语义 | `test_script_conversion.ScriptConversion.test_continuous_pages_preserve_gray_spacing_detached_marks_and_pale_short_ending`；`test_public_contracts.ScriptPublicContracts.test_remote_script_matrix_preserves_source_pages_and_honest_completion`。连续像素与跨页比例由核心实际 PDF 测试验证；公共矩阵验证各入口走同一实现及全部页，不声称对每入口重复逐像素校验。 |
| `test_public_contracts.PublicContracts.test_every_group_entry_splits_defaults_and_rejects_new_oversized_or_unreadable_groups` | 语义迁移 | 模型组切分退出；新核心图像资源上限与不可读失败保留 | `test_public_contracts.ScriptPublicContracts.test_script_entries_apply_input_resource_limit_before_decoding`；`test_public_contracts.ScriptPublicContracts.test_script_entries_publish_all_pages_or_no_result_for_black_input`；`test_script_conversion.ScriptConversion.test_memory_and_temporary_disk_budgets_fail_without_partial_publication` |

## test_public_contracts.ScriptPublicContracts

| 旧测试 ID | 实际处理 | 保留语义或退役原因 | 当前测试或证据 |
| --- | --- | --- | --- |
| `test_public_contracts.ScriptPublicContracts.test_script_entries_keep_complete_result_when_temporary_cleanup_fails` | 原 ID 保留 | 发布已完成时清理失败不撤回成功，不破坏已发布完整结果 | `test_public_contracts.ScriptPublicContracts.test_script_entries_keep_complete_result_when_temporary_cleanup_fails` |
| `test_public_contracts.ScriptPublicContracts.test_script_entries_normalize_temporary_allocation_errors` | 原 ID 保留 | 临时目录分配错误在Python/CLI/HTTP均脱敏且无traceback | `test_public_contracts.ScriptPublicContracts.test_script_entries_normalize_temporary_allocation_errors` |
| `test_public_contracts.ScriptPublicContracts.test_script_entries_preserve_specific_error_when_temporary_cleanup_fails` | 原 ID 保留 | 已有具体ConversionError不被后续清理错误覆盖 | `test_public_contracts.ScriptPublicContracts.test_script_entries_preserve_specific_error_when_temporary_cleanup_fails` |
| `test_public_contracts.ScriptPublicContracts.test_script_entries_normalize_output_parent_filesystem_errors` | 原 ID 保留 | 输出父路径文件系统错误保持稳定错误码且无私有路径 | `test_public_contracts.ScriptPublicContracts.test_script_entries_normalize_output_parent_filesystem_errors` |
| `test_public_contracts.ScriptPublicContracts.test_script_entries_apply_input_resource_limit_before_decoding` | 原 ID 保留 | 输入字节超额在探测/解码前拒绝，各入口一致 | `test_public_contracts.ScriptPublicContracts.test_script_entries_apply_input_resource_limit_before_decoding` |
| `test_public_contracts.ScriptPublicContracts.test_script_entries_reject_existing_paths_and_invalid_source` | 原 ID 保留 | 已有输出不覆盖，非法来源无产物发布 | `test_public_contracts.ScriptPublicContracts.test_script_entries_reject_existing_paths_and_invalid_source` |
| `test_public_contracts.ScriptPublicContracts.test_script_entries_publish_all_pages_or_no_result_for_black_input` | 原 ID 保留 | 全黑/无谱失败不发布；成功必须完整PDF及全部有序预览 | `test_public_contracts.ScriptPublicContracts.test_script_entries_publish_all_pages_or_no_result_for_black_input` |

## test_reconstruction.LocalScoreWorkflow

| 旧测试 ID | 实际处理 | 保留语义或退役原因 | 当前测试或证据 |
| --- | --- | --- | --- |
| `test_reconstruction.LocalScoreWorkflow.test_capture_and_record_writes_reject_external_symlinks` | 语义迁移 | 旧capture/record退出；服务清理与产物映射拒绝外部symlink/穿越 | `test_web_worker.WebsiteWorker.test_artifact_symlink_is_refused_without_reading_outside_task`；`test_product_lifecycle.ProductLifecycle.test_cleanup_preserves_unknown_files_replaced_inodes_and_external_symlinks`；`test_product_lifecycle.ProductLifecycle.test_cleanup_rejects_replaced_attempt_and_parent_symlink` |
| `test_reconstruction.LocalScoreWorkflow.test_local_video_delivers_reviewed_named_vector_pdf` | 专属退役 | 人工谱名/矢量/审核输出退出；新本地PDF正常路径已有公开测试 | 无，旧专属功能退出。 |
| `test_reconstruction.LocalScoreWorkflow.test_corrupt_redraw_is_rejected_on_resume` | 专属退役 | 宿主重绘恢复退出；产物损坏由最终服务文件完整性另约束 | 无，旧专属功能退出。 |
| `test_reconstruction.LocalScoreWorkflow.test_invalid_local_media_has_no_success_record` | 语义迁移 | 非法本地媒体失败且无最终产物 | `test_public_contracts.ScriptPublicContracts.test_script_entries_reject_existing_paths_and_invalid_source` |
| `test_reconstruction.LocalScoreWorkflow.test_corrupt_original_or_crop_blocks_delivery` | 语义迁移 | 人工crop退出；实际source变化或坏产物不交付 | `test_script_conversion.ScriptConversion.test_changed_source_is_rejected_without_publishing_or_touching_other_results`；`test_product_lifecycle.ProductLifecycle.test_corrupt_same_size_artifact_is_not_served` |
| `test_reconstruction.LocalScoreWorkflow.test_unresolved_notation_cannot_be_exported` | 语义迁移 | 人工未决表退出；程序已确认缺段/歧义明确失败 | `test_script_conversion.ScriptConversion.test_native_motion_between_identical_samples_never_publishes_shortened_score`；`test_script_conversion.ScriptConversion.test_detected_page_flip_does_not_silently_publish_only_first_page` |
| `test_reconstruction.LocalScoreWorkflow.test_failed_new_selection_preserves_previous_work` | 语义迁移 | 人工重选退出；失败任务/重试不得替换旧产物或他人文件 | `test_public_contracts.ScriptPublicContracts.test_script_entries_reject_existing_paths_and_invalid_source`；`test_media_boundary.MediaBoundaryTests.test_decode_failure_preserves_existing_output_and_charges_attempt_budget` |
| `test_reconstruction.LocalScoreWorkflow.test_existing_user_directory_is_preserved` | 语义迁移 | 已有输出目录/未知文件绝不覆盖 | `test_public_contracts.ScriptPublicContracts.test_script_entries_reject_existing_paths_and_invalid_source` |
| `test_reconstruction.LocalScoreWorkflow.test_failed_seek_keeps_actual_consumed_budget` | 语义迁移，实测预算 | 旧跨请求累计seek预算退出；同任务真实解码时间仍计入总预算 | `test_media_boundary.MediaBoundaryTests.test_decode_failure_preserves_existing_output_and_charges_attempt_budget`；`test_script_conversion.ScriptConversion.test_total_deadline_stops_child_decoder_and_cleans_owned_temporary_root`；`test_media_boundary.MediaBoundaryTests.test_failed_decoders_charge_real_elapsed_and_exhaust_remaining_budget`；B-73，真实失败耗时累计、剩余预算停止及耗尽不启动；手填 60 不作实测。 |
| `test_reconstruction.LocalScoreWorkflow.test_repeated_music_and_short_ending_keep_order_across_a4_pages` | 语义迁移 | 不同位置重复音乐、短尾及页间顺序完整 | `test_script_conversion.ScriptConversion.test_identical_music_at_later_scroll_positions_is_retained`；`test_script_conversion.ScriptConversion.test_repeated_music_with_small_measure_numbers_retains_fast_scroll_positions`；`test_script_conversion.ScriptConversion.test_continuous_pages_preserve_gray_spacing_detached_marks_and_pale_short_ending` |
| `test_reconstruction.LocalScoreWorkflow.test_reselect_same_title_preserves_old_pdf_and_unknown_user_file` | 语义迁移 | 重选/同谱名接口退出；已有PDF及未知文件不覆盖 | `test_public_contracts.ScriptPublicContracts.test_script_entries_reject_existing_paths_and_invalid_source`；`test_public_contracts.ScriptPublicContracts.test_public_cli_parsers_do_not_echo_invalid_arguments_or_private_payload` |
| `test_reconstruction.LocalScoreWorkflow.test_resume_after_export_record_write_interrupt_preserves_sources_and_budget` | 语义迁移 | 旧导出record/审批恢复退出；文件发布/SQLite崩溃窗口恢复不伪造成功 | `test_web_worker.WebsiteWorker.test_durable_finishing_wins_cancel_and_recovers_after_real_sigkill`；`test_web_worker.WebsiteWorker.test_lost_database_commit_acknowledgement_cannot_delete_committed_result` |

## test_score_workflow.ScoreWorkflow

| 旧测试 ID | 实际处理 | 保留语义或退役原因 | 当前测试或证据 |
| --- | --- | --- | --- |
| `test_score_workflow.ScoreWorkflow.test_resolved_source_review_restores_same_selection_export` | 专属退役 | 旧宿主重绘/人工选行/审阅撤回/修正预算与路线恢复功能退出。 | 无，旧专属功能退出。 |
| `test_score_workflow.ScoreWorkflow.test_same_selection_withdrawal_preserves_consumed_correction` | 专属退役 | 旧宿主重绘/人工选行/审阅撤回/修正预算与路线恢复功能退出。 | 无，旧专属功能退出。 |
| `test_score_workflow.ScoreWorkflow.test_local_reselection_preserves_same_budget_and_invalidates_changed_material` | 专属退役 | 旧宿主重绘/人工选行/审阅撤回/修正预算与路线恢复功能退出。 | 无，旧专属功能退出。 |
| `test_score_workflow.ScoreWorkflow.test_default_generation_groups_are_independent_of_print_pages` | 专属退役 | 旧宿主重绘/人工选行/审阅撤回/修正预算与路线恢复功能退出。 | 无，旧专属功能退出。 |
| `test_score_workflow.ScoreWorkflow.test_withdrawn_source_review_blocks_new_host_calls` | 专属退役 | 旧宿主重绘/人工选行/审阅撤回/修正预算与路线恢复功能退出。 | 无，旧专属功能退出。 |
| `test_score_workflow.ScoreWorkflow.test_interrupted_capture_publication_preserves_orphan_and_can_resume` | 语义迁移 | 人工capture恢复退出；进程中断不误删外部文件、不发布半成品 | `test_script_conversion.ScriptConversion.test_killed_caller_leaves_no_active_decoder_or_task_temporary_root`；`test_product_lifecycle.ProductLifecycle.test_cleanup_preserves_unknown_files_replaced_inodes_and_external_symlinks`；`test_web_worker.WebsiteWorker.test_sigkill_guardian_holds_lock_until_cleanup_then_restart_marks_interrupted` |
| `test_score_workflow.ScoreWorkflow.test_custom_redraw_group_cannot_bypass_pixel_limit` | 语义迁移 | 自定生图组退出；各最终入口不允许绕过资源上限 | `test_public_contracts.ScriptPublicContracts.test_script_entries_apply_input_resource_limit_before_decoding`；`test_script_conversion.ScriptConversion.test_memory_and_temporary_disk_budgets_fail_without_partial_publication` |
| `test_score_workflow.ScoreWorkflow.test_late_notation_rejection_invalidates_approved_pdf_and_preserves_one_correction` | 专属退役 | 旧宿主重绘/人工选行/审阅撤回/修正预算与路线恢复功能退出。 | 无，旧专属功能退出。 |
| `test_score_workflow.ScoreWorkflow.test_late_rejection_after_consumed_correction_exports_vector_without_budget_reset` | 专属退役 | 旧宿主重绘/人工选行/审阅撤回/修正预算与路线恢复功能退出。 | 无，旧专属功能退出。 |
| `test_score_workflow.ScoreWorkflow.test_same_selection_resume_keeps_consumed_correction_and_accepted_output` | 专属退役 | 旧宿主重绘/人工选行/审阅撤回/修正预算与路线恢复功能退出。 | 无，旧专属功能退出。 |
| `test_score_workflow.ScoreWorkflow.test_changed_selection_cannot_resume_old_accepted_redraw_after_interruption` | 专属退役 | 旧宿主重绘/人工选行/审阅撤回/修正预算与路线恢复功能退出。 | 无，旧专属功能退出。 |
| `test_score_workflow.ScoreWorkflow.test_final_pdf_approval_rejects_corrupt_generated_or_navigation_artifacts` | 语义迁移 | 生成/导航/审核退出；最终PDF与预览损坏不当有效产物提供 | `test_product_lifecycle.ProductLifecycle.test_corrupt_same_size_artifact_is_not_served`；`test_web_worker.WebsiteWorker.test_preview_tool_failure_never_completes_or_serves_partial_result` |
| `test_score_workflow.ScoreWorkflow.test_local_entry_validates_workflow_artifacts_before_resume_or_approval` | 语义迁移 | 旧批准恢复退出；真实产物映射及hash保持可验证 | `test_product_lifecycle.ProductLifecycle.test_corrupt_same_size_artifact_is_not_served`；`test_web_worker.WebsiteWorker.test_artifact_symlink_is_refused_without_reading_outside_task` |
| `test_score_workflow.ScoreWorkflow.test_mixed_routes_preserve_long_score_order_and_unresolved_sources_block_export` | 语义迁移 | 混合重绘路线退出；长谱顺序及已知未决失败保留 | `test_script_conversion.ScriptConversion.test_scrolling_preserves_every_position_and_full_endpoints`；`test_script_conversion.ScriptConversion.test_native_motion_between_identical_samples_never_publishes_shortened_score` |
| `test_score_workflow.ScoreWorkflow.test_generated_pages_with_different_native_resolutions_share_source_print_width` | 语义迁移 | 生成图native尺寸入口退出；A4统一源宽比例保留 | `test_script_conversion.ScriptConversion.test_continuous_pages_preserve_gray_spacing_detached_marks_and_pale_short_ending`。生成图多分辨率输入退出；验证当前连续原图的实际跨页 placement，图宽及 x/y ppi 一致。 |
| `test_score_workflow.ScoreWorkflow.test_url_resume_normalizes_equivalent_public_urls_without_acquisition` | 语义迁移 | 旧prepare resume不再支持；合法BV/p规范化和重试来源绑定保留 | `test_script_conversion.ScriptConversion.test_public_link_validation_retains_partition_and_rejects_nonpublic_input`；`test_web.WebsiteHTTP.test_retry_uses_original_capability_and_current_ip_quota` |
| `test_score_workflow.ScoreWorkflow.test_large_rough_is_chunked_without_dropping_systems` | 语义迁移 | 旧rough导航切块退出；有界长谱处理不遗漏系统 | `test_script_conversion.ScriptConversion.test_scrolling_preserves_every_position_and_full_endpoints`；`test_script_conversion.ScriptConversion.test_repeated_music_with_small_measure_numbers_retains_fast_scroll_positions` |
| `test_score_workflow.ScoreWorkflow.test_navigation_preserves_only_agent_requested_native_captures` | 专属退役 | Agent点选原生导航及其保留策略退出；线上保留由#73生命周期定义 | 无，旧专属功能退出。 |
| `test_score_workflow.ScoreWorkflow.test_redraw_correction_budget_survives_resume_and_rejection_falls_back` | 专属退役 | 旧宿主重绘/人工选行/审阅撤回/修正预算与路线恢复功能退出。 | 无，旧专属功能退出。 |
| `test_score_workflow.ScoreWorkflow.test_distinct_positions_keep_repeated_music_and_same_position_overlap_is_removed` | 语义迁移 | 同位置停驻去重，不同位置重复必须保留或歧义明确失败 | `test_script_conversion.ScriptConversion.test_identical_music_at_later_scroll_positions_is_retained`；`test_script_conversion.ScriptConversion.test_repeated_music_with_small_measure_numbers_retains_fast_scroll_positions`；`test_script_conversion.ScriptConversion.test_native_motion_between_identical_samples_never_publishes_shortened_score` |
| `test_score_workflow.ScoreWorkflow.test_generated_native_content_reflows_after_explicit_boundary_review` | 专属退役 | 生图重排及人工边界审核退出；自动整组分页另保留 | 无，旧专属功能退出。 |

## test_script_comparison.ScriptComparison

| 旧测试 ID | 实际处理 | 保留语义或退役原因 | 当前测试或证据 |
| --- | --- | --- | --- |
| `test_script_comparison.ScriptComparison.test_existing_results_are_preserved_and_deadline_stops_program` | 原 ID 保留 | 实验输出不覆盖，受控外部程序总期限与退出清理 | `test_script_comparison.ScriptComparison.test_existing_results_are_preserved_and_deadline_stops_program` |
| `test_script_comparison.ScriptComparison.test_changed_fixed_input_is_refused_without_starting_program` | 原 ID 保留 | 冻结输入hash变化先拒绝，不运行比较且保留原证据 | `test_script_comparison.ScriptComparison.test_changed_fixed_input_is_refused_without_starting_program` |
| `test_script_comparison.ScriptComparison.test_optimized_version_requires_matching_clean_checkout` | 原 ID 保留 | 比较源码版本/干净状态绑定，不能把漂移代码称固定版本 | `test_script_comparison.ScriptComparison.test_optimized_version_requires_matching_clean_checkout` |

## test_script_conversion.ScriptConversion

| 旧测试 ID | 实际处理 | 保留语义或退役原因 | 当前测试或证据 |
| --- | --- | --- | --- |
| `test_script_conversion.ScriptConversion.test_page_balancing_moves_whole_groups_to_sparse_final_page` | 原 ID 保留 | 整行组连续均衡分页，尾页不靠裁断或拉伸填充 | `test_script_conversion.ScriptConversion.test_page_balancing_moves_whole_groups_to_sparse_final_page` |
| `test_script_conversion.ScriptConversion.test_source_size_limit_is_checked_before_probe` | 原 ID 保留 | 实际来源字节上限在媒体探测前执行 | `test_script_conversion.ScriptConversion.test_source_size_limit_is_checked_before_probe` |
| `test_script_conversion.ScriptConversion.test_memory_and_temporary_disk_budgets_fail_without_partial_publication` | 原 ID 保留 | RSS/暂存超额明确失败、无半成品且来源不变 | `test_script_conversion.ScriptConversion.test_memory_and_temporary_disk_budgets_fail_without_partial_publication` |
| `test_script_conversion.ScriptConversion.test_total_deadline_stops_child_decoder_and_cleans_owned_temporary_root` | 原 ID 保留 | 总期限停止真实解码子进程并清理受管暂存 | `test_script_conversion.ScriptConversion.test_total_deadline_stops_child_decoder_and_cleans_owned_temporary_root` |
| `test_script_conversion.ScriptConversion.test_abnormal_conversion_worker_stops_its_independent_session_descendant` | 原 ID 保留 | 转换进程异常退出后独立session后代也停止 | `test_script_conversion.ScriptConversion.test_abnormal_conversion_worker_stops_its_independent_session_descendant` |
| `test_script_conversion.ScriptConversion.test_killed_caller_leaves_no_active_decoder_or_task_temporary_root` | 原 ID 保留 | 调用方SIGKILL后guardian回收实际后代与本任务暂存 | `test_script_conversion.ScriptConversion.test_killed_caller_leaves_no_active_decoder_or_task_temporary_root` |
| `test_script_conversion.ScriptConversion.test_cancelled_conversion_does_not_publish_or_leave_staging` | 原 ID 保留 | 公开取消触发真实退出、无结果与暂存残留 | `test_script_conversion.ScriptConversion.test_cancelled_conversion_does_not_publish_or_leave_staging` |
| `test_script_conversion.ScriptConversion.test_invalid_input_never_publishes_or_overwrites` | 原 ID 保留 | 坏媒体/缺来源无输出，已有用户输出不覆盖 | `test_script_conversion.ScriptConversion.test_invalid_input_never_publishes_or_overwrites` |
| `test_script_conversion.ScriptConversion.test_cli_errors_are_json_without_private_path_or_partial_output` | 原 ID 保留 | CLI稳定JSON/退出码2，禁止私有路径和traceback | `test_script_conversion.ScriptConversion.test_cli_errors_are_json_without_private_path_or_partial_output` |
| `test_script_conversion.ScriptConversion.test_public_link_validation_retains_partition_and_rejects_nonpublic_input` | 原 ID 保留 | 规范HTTPS BV与正分P，拒绝本地/私网链接 | `test_script_conversion.ScriptConversion.test_public_link_validation_retains_partition_and_rejects_nonpublic_input` |
| `test_script_conversion.ScriptConversion.test_static_video_produces_complete_a4_pages_and_actual_source_records` | 原 ID 保留 | 无损静态原像素/A4/全页/实际PTS/hash/不称音乐校对 | `test_script_conversion.ScriptConversion.test_static_video_produces_complete_a4_pages_and_actual_source_records` |
| `test_script_conversion.ScriptConversion.test_scrolling_preserves_every_position_and_full_endpoints` | 原 ID 保留 | 完整首尾、中间七行和真实时间，不丢位置 | `test_script_conversion.ScriptConversion.test_scrolling_preserves_every_position_and_full_endpoints` |
| `test_script_conversion.ScriptConversion.test_detected_page_flip_does_not_silently_publish_only_first_page` | 原 ID 保留 | 已检测翻页断续明确失败，不把首屏当完整曲谱 | `test_script_conversion.ScriptConversion.test_detected_page_flip_does_not_silently_publish_only_first_page` |
| `test_script_conversion.ScriptConversion.test_identical_music_at_later_scroll_positions_is_retained` | 原 ID 保留 | 不同位置相同音乐慢滚完整保留，原像素一致 | `test_script_conversion.ScriptConversion.test_identical_music_at_later_scroll_positions_is_retained` |
| `test_script_conversion.ScriptConversion.test_native_motion_between_identical_samples_never_publishes_shortened_score` | 原 ID 保留 | 两速度×FFV1/H264四周期混叠明确拒绝，不发布已知缩短结果 | `test_script_conversion.ScriptConversion.test_native_motion_between_identical_samples_never_publishes_shortened_score` |
| `test_script_conversion.ScriptConversion.test_static_lossy_video_does_not_invent_scroll_from_compression_changes` | 原 ID 保留 | 有损静态压缩变化不虚构位移或重复扩展 | `test_script_conversion.ScriptConversion.test_static_lossy_video_does_not_invent_scroll_from_compression_changes` |
| `test_script_conversion.ScriptConversion.test_changing_background_keeps_unambiguous_stationary_score` | 原 ID 保留 | 显著动态背景但谱面位置唯一时允许静态谱完成 | `test_script_conversion.ScriptConversion.test_changing_background_keeps_unambiguous_stationary_score` |
| `test_script_conversion.ScriptConversion.test_native_tail_pts_regression_keeps_decoder_order_and_real_timestamps` | 原 ID 保留 | 真实尾PTS回退保持解码顺序与原值，不排序/估算 | `test_script_conversion.ScriptConversion.test_native_tail_pts_regression_keeps_decoder_order_and_real_timestamps` |
| `test_script_conversion.ScriptConversion.test_repeated_music_with_small_measure_numbers_retains_fast_scroll_positions` | 原 ID 保留 | 带微小小节号的七行快滚保留完整累计位置 | `test_script_conversion.ScriptConversion.test_repeated_music_with_small_measure_numbers_retains_fast_scroll_positions` |
| `test_script_conversion.ScriptConversion.test_no_safe_gap_preserves_tall_group_without_hard_cut` | 原 ID 保留 | 彩色关联记号连接的超高组完整等比缩小，不硬切 | `test_script_conversion.ScriptConversion.test_no_safe_gap_preserves_tall_group_without_hard_cut` |

## test_skill_install.SkillInstallTests

| 旧测试 ID | 实际处理 | 保留语义或退役原因 | 当前测试或证据 |
| --- | --- | --- | --- |
| `test_skill_install.SkillInstallTests.test_utf8_snapshot_portable_keys_and_strict_old_manifest_paths` | 专属退役 | 旧Skill安装/发现/升级/回滚工具退出；不为测试恢复自动卸载或读取真实宿主目录。服务路径与备份另有新边界。 | 无，旧专属功能退出。 |
| `test_skill_install.SkillInstallTests.test_windows_short_paths_install_upgrade_and_rollback` | 专属退役 | 旧Skill安装/发现/升级/回滚工具退出；不为测试恢复自动卸载或读取真实宿主目录。服务路径与备份另有新边界。 | 无，旧专属功能退出。 |
| `test_skill_install.SkillInstallTests.test_windows_junctions_are_rejected_at_root_ancestor_and_managed_directory` | 专属退役 | 旧Skill安装/发现/升级/回滚工具退出；不为测试恢复自动卸载或读取真实宿主目录。服务路径与备份另有新边界。 | 无，旧专属功能退出。 |
| `test_skill_install.SkillInstallTests.test_committed_snapshot_single_entry_and_repeat_is_noop` | 专属退役 | 旧Skill安装/发现/升级/回滚工具退出；不为测试恢复自动卸载或读取真实宿主目录。服务路径与备份另有新边界。 | 无，旧专属功能退出。 |
| `test_skill_install.SkillInstallTests.test_source_symlink_rejected_without_replacing_valid_install` | 专属退役 | 旧Skill安装/发现/升级/回滚工具退出；不为测试恢复自动卸载或读取真实宿主目录。服务路径与备份另有新边界。 | 无，旧专属功能退出。 |
| `test_skill_install.SkillInstallTests.test_update_preserves_tasks_and_rollback_restores_old_version` | 专属退役 | 旧Skill安装/发现/升级/回滚工具退出；不为测试恢复自动卸载或读取真实宿主目录。服务路径与备份另有新边界。 | 无，旧专属功能退出。 |
| `test_skill_install.SkillInstallTests.test_failed_publication_restores_install_and_unmanaged_tasks` | 专属退役 | 旧Skill安装/发现/升级/回滚工具退出；不为测试恢复自动卸载或读取真实宿主目录。服务路径与备份另有新边界。 | 无，旧专属功能退出。 |
| `test_skill_install.SkillInstallTests.test_legacy_duplicate_layout_migrates_with_original_backup` | 专属退役 | 旧Skill安装/发现/升级/回滚工具退出；不为测试恢复自动卸载或读取真实宿主目录。服务路径与备份另有新边界。 | 无，旧专属功能退出。 |
| `test_skill_install.SkillInstallTests.test_failed_restoration_keeps_user_task_in_recoverable_staging` | 专属退役 | 旧Skill安装/发现/升级/回滚工具退出；不为测试恢复自动卸载或读取真实宿主目录。服务路径与备份另有新边界。 | 无，旧专属功能退出。 |
| `test_skill_install.SkillInstallTests.test_rollback_rejects_a_backup_for_another_installation` | 专属退役 | 旧Skill安装/发现/升级/回滚工具退出；不为测试恢复自动卸载或读取真实宿主目录。服务路径与备份另有新边界。 | 无，旧专属功能退出。 |
| `test_skill_install.SkillInstallTests.test_corrupt_managed_file_is_reported_instead_of_noop` | 专属退役 | 旧Skill安装/发现/升级/回滚工具退出；不为测试恢复自动卸载或读取真实宿主目录。服务路径与备份另有新边界。 | 无，旧专属功能退出。 |
| `test_skill_install.SkillInstallTests.test_manifest_escape_symlink_and_unmanaged_collision_leave_old_install` | 专属退役 | 旧Skill安装/发现/升级/回滚工具退出；不为测试恢复自动卸载或读取真实宿主目录。服务路径与备份另有新边界。 | 无，旧专属功能退出。 |

## test_skill_package.SkillPackageTests

| 旧测试 ID | 实际处理 | 保留语义或退役原因 | 当前测试或证据 |
| --- | --- | --- | --- |
| `test_skill_package.SkillPackageTests.test_protocols_are_current_and_all_local_links_stay_in_package` | 语义迁移，安装实证 | Skill协议同步退出；wheel静态资源与必要运行文件齐备、文档链接指向新产品 | I-73，20 文件及静态资源字节已核对，提交绑定见 `product73-packaging/final-binding.json`；旧 Skill 包内协议和相对链接同步机制退出。 |
| `test_skill_package.SkillPackageTests.test_detached_directory_cli_and_synthetic_pdf_replay` | 语义迁移，安装实证 | 仓库外安装后CLI/实际转换/全部预览成功，不依赖源码目录 | I-73，仓库外基础 CLI 与 web/worker spawn 转换、全部预览及依赖检查已记录，提交绑定见 `product73-packaging/final-binding.json`。 |

## test_stage_cli.RevisionCLI

| 旧测试 ID | 实际处理 | 保留语义或退役原因 | 当前测试或证据 |
| --- | --- | --- | --- |
| `test_stage_cli.RevisionCLI.test_local_source_revision_and_return_restore_unknown_call_and_other_group` | 专属退役 | 旧 stage、手工分组、模型调用/修正预算和最终审核版本协议退出。 | 无，旧专属功能退出。 |
| `test_stage_cli.RevisionCLI.test_batch_requests_include_new_prepared_and_legacy_calling_groups` | 专属退役 | 旧 stage、手工分组、模型调用/修正预算和最终审核版本协议退出。 | 无，旧专属功能退出。 |
| `test_stage_cli.RevisionCLI.test_crop_change_cancels_only_unsubmitted_history` | 专属退役 | 旧 stage、手工分组、模型调用/修正预算和最终审核版本协议退出。 | 无，旧专属功能退出。 |
| `test_stage_cli.RevisionCLI.test_layout_reuses_materials_and_renders_every_revision_page` | 语义迁移 | 旧layout revision复用退出；所有当前页预览齐全再发布 | `test_public_contracts.ScriptPublicContracts.test_remote_script_matrix_preserves_source_pages_and_honest_completion` |
| `test_stage_cli.RevisionCLI.test_stage_advances_synthetic_video_and_never_reissues_pending_host_call` | 专属退役 | 旧 stage、手工分组、模型调用/修正预算和最终审核版本协议退出。 | 无，旧专属功能退出。 |
| `test_stage_cli.RevisionCLI.test_regrouping_restores_exact_membership_and_spent_version_budget` | 专属退役 | 旧 stage、手工分组、模型调用/修正预算和最终审核版本协议退出。 | 无，旧专属功能退出。 |
| `test_stage_cli.RevisionCLI.test_manual_frozen_stage_requires_genuine_input_review_without_new_scan` | 专属退役 | 旧 stage、手工分组、模型调用/修正预算和最终审核版本协议退出。 | 无，旧专属功能退出。 |
| `test_stage_cli.RevisionCLI.test_exact_history_membership_remaps_accepted_rows_after_insertion` | 专属退役 | 旧 stage、手工分组、模型调用/修正预算和最终审核版本协议退出。 | 无，旧专属功能退出。 |
| `test_stage_cli.RevisionCLI.test_publication_failure_keeps_valid_selection_and_pending_budget` | 语义迁移 | 选择/模型预算退出；发布失败不覆盖有效结果与来源 | `test_public_contracts.ScriptPublicContracts.test_script_entries_reject_existing_paths_and_invalid_source`；`test_public_contracts.ScriptPublicContracts.test_entries_do_not_publish_pdf_when_page_preview_tool_fails`；`test_web_worker.WebsiteWorker.test_preview_tool_failure_never_completes_or_serves_partial_result` |
| `test_stage_cli.RevisionCLI.test_preview_failure_does_not_publish_an_unreviewable_pdf` | 语义迁移 | 真实渲染失败不能发布缺页结果 | `test_public_contracts.ScriptPublicContracts.test_entries_do_not_publish_pdf_when_page_preview_tool_fails`；`test_web_worker.WebsiteWorker.test_preview_tool_failure_never_completes_or_serves_partial_result` |
| `test_stage_cli.RevisionCLI.test_regrouping_after_final_review_invalidates_pdf_and_keeps_exact_group` | 专属退役 | 旧 stage、手工分组、模型调用/修正预算和最终审核版本协议退出。 | 无，旧专属功能退出。 |
| `test_stage_cli.RevisionCLI.test_pdf_review_requires_explicit_current_revision_after_layout_change` | 专属退役 | 旧 stage、手工分组、模型调用/修正预算和最终审核版本协议退出。 | 无，旧专属功能退出。 |
| `test_stage_cli.RevisionCLI.test_public_vector_export_obeys_layout_and_produces_reviewable_pages` | 专属退役 | 旧 stage、手工分组、模型调用/修正预算和最终审核版本协议退出。 | 无，旧专属功能退出。 |
| `test_stage_cli.RevisionCLI.test_legacy_pdf_without_all_previews_or_checks_cannot_be_approved` | 语义迁移 | Agent批准退出；没有全部当前预览不complete/不提供下载 | `test_public_contracts.ScriptPublicContracts.test_remote_script_matrix_preserves_source_pages_and_honest_completion`；`test_web_worker.WebsiteWorker.test_preview_tool_failure_never_completes_or_serves_partial_result` |
| `test_stage_cli.RevisionCLI.test_new_explicit_group_and_single_unreadable_row_reject_host_input` | 专属退役 | 旧 stage、手工分组、模型调用/修正预算和最终审核版本协议退出。 | 无，旧专属功能退出。 |
| `test_stage_cli.RevisionCLI.test_same_pdf_bytes_new_export_rejects_old_revision_token` | 专属退役 | 旧 stage、手工分组、模型调用/修正预算和最终审核版本协议退出。 | 无，旧专属功能退出。 |
| `test_stage_cli.RevisionCLI.test_legacy_large_accepted_identity_retains_materials_and_spent_budget` | 专属退役 | 旧 stage、手工分组、模型调用/修正预算和最终审核版本协议退出。 | 无，旧专属功能退出。 |
| `test_stage_cli.RevisionCLI.test_stage_upgrades_legacy_hash_review_and_requires_new_page_review` | 专属退役 | 旧 stage、手工分组、模型调用/修正预算和最终审核版本协议退出。 | 无，旧专属功能退出。 |

## 审计快照与剩余核对

实施者最终运行记录为 `/home/kenqia/issue69-context/full73-budget-final.log`，131 项、109.065 秒、无跳过，结果 `OK`。最终结果包含真实预算补证后的新鲜全量，先前 130 项结果保留在 `full73-final.log`。`/home/kenqia/issue69-context/shards73-budget-final.json` 记录发现 131 项，两个分片为 66/65 项、无交集且穷尽。`/home/kenqia/issue69-context/ci73-final/summary.json` 记录三行合成谱面一页 PDF、双跑相同、已有输出和资源超限拒绝；其评价范围为合成图像产品，不是音乐校对或真实来源验收。上述记录仍须与最终提交绑定。

上表共 217 行，旧 ID 唯一且完整。处理统计为原 ID 保留 88、语义迁移 57、专属退役 65、专属退役，条件未触发 1、语义迁移，安装实证 3、语义迁移，静态配置 1、语义迁移，实测预算 2。统计描述迁移去向，不是运行通过数。

编写时当前测试有 131 个直接定义的方法。按 `tests/test_*.py` 文件名排序构造逐文件 SHA256 字典，再对排序 JSON 计算 SHA256，得到 `4f78a7387bc14d5b38e64a76005c9ec29f7457e55b9f60d9562b383701f4e08b`。源码继续修改后需重新检查目标 ID；不把方法数减少当作安全保护已退役的理由。

`I-73` 的独立安装与 `B-73` 的真实累计耗时后果已记录，最终提交绑定由外部 `product73-packaging/final-binding.json` 提供。旧跨 stage 累计协议退出，真实总期限测试另保留任务级停止保护，不与解码累计测量混为一谈。最终提交、定向运行和独立 merger 复核完成前，不用本页替代合并门槛。

映射初稿由独立预检者编写，实施者补入真实预算测量和最终提交绑定位置。没有修改已安装 Skill 或原工作区，没有远端写入。


## BBDownNext 2.3.0 入口替换

2026-10-22 的后续接入用固定 BBDownNext CLI 替换 yt-dlp 解析器，保留原 Python 媒体传输。此节修订上表关于旧下载器实现的描述，旧测试 ID 继续作为历史清单，不声称所有旧名称仍存在。

| 旧实现契约 | 当前验证与处理 |
| --- | --- |
| yt-dlp 原生 DASH、最佳独立视频轨、单文件回退、实际分辨率 | `test_link_input` 的同类测试通过真实合成 BBDown 子进程和 FFprobe/FFmpeg 验证。 |
| 公开元数据与 BV、aid、CID、分 P、完整曲长绑定 | `test_api_acquisition` 使用完整 view/player JSON、唯一 playurl 文件和匹配请求，缺失、重复、截断或受限来源拒绝传输媒体。 |
| DNS 固定、TLS 主机名、IPv6 不可达后备、重定向及同轨备份 | 原 Python 媒体传输测试保留；`test_bbdown_network` 覆盖元数据 CONNECT 的全部 DNS 地址、数值 IP、目标白名单与清理。 |
| 环境代理及恢复路径 | 用户要求保持直连，该生产行为退出。替代测试确认媒体忽略代理，CLI 仅使用任务内直连校验中继，不读系统代理或改路由。 |
| 下载器配置、Cookie、netrc、插件隔离 | 合成可执行文件旁放置测试标记，验证新 AppDir、空配置、干净 HOME/env，不读任何真实凭据。yt-dlp 插件构造器随依赖退役。 |
| 元数据压缩体读取限额 | 不再使用 Python 的旧 `BoundedBody`。新构建的 C# HTTP 读取循环限制解压后响应 2 MiB，Python 限制 CLI 总输出及 playurl 文件各 2 MiB，中继限制隧道字节。具体构建验证单独记录，不能以旧未调用测试冒充新路径证据。 |
| 获取、探测、复制期限，SIGTERM、父进程退出与孙进程 | `test_acquisition_lifecycle` 保留六项真实进程/信号测试，并记录实际 CLI 与孙进程 PID；恢复阶段改为直连元数据阻塞。 |
| Python、CLI、HTTP 的公开契约 | `test_public_contracts` 的共同矩阵承接成功、依赖缺失、非公共目标和失败不发布；HTTP 仍只接收公开链接。 |

所有新增测试只使用合成标记、离线 DNS/HTTP 边界和假 CLI，不读取用户凭据，不作为真实云端转换通过的替代证据。

## 八路并行改造

原串行 worker 测试保留，用默认并行度 1 继续验证第二调度器拒绝、10 等待加 1 活动、取消与恢复。新增八路真实进程重叠、多 guardian 持锁、并行停止、回执丢失隔离、原子名额和空间预留测试。未知 schema 合成标记从版本 2 改为 999，避免与新版本冲突，仍保留未知版本拒绝及源不变断言。`upgrade-v1` 另验证多页结果 hash、原期限、新 inode 与清理；没有删除旧测试。

## 可调整打印排版

2026-10-24，默认 PDF 从连续条带改为完整行组紧凑排列。test_static_video_produces_complete_a4_pages_and_actual_source_records 将单图尺寸恒等断言迁为所有实际嵌入图的完整非白像素集合恒等，并保留原来源、PTS、页面比例等断言。test_continuous_pages_preserve_gray_spacing_detached_marks_and_pale_short_ending 保留跨页统一比例、完整来源范围、灰背景和彩色记号，将一页一图假设迁为按实际嵌入顺序逐像素重建原图；没有删除测试。不可拆分行组仍核验完整单图。维护备份多页测试的合成谱面扩至十七行，继续实际验证多页恢复，不把更紧凑的一页结果当作多页证据。新增 test_print_layout 和公开 HTTP 契约覆盖页数增减、重复谱行、彩色记号、源结果不变和期限。



## Issue #85 缓存获取边界

旧`test_web_worker.BACKEND`只替换匿名下载，新增来源预检后会意外调用真实BBDown。该fixture现同时提供匿名元数据检查，明确返回无可证明媒体版本，继续原有普通下载与独立进程树验证。维护恢复fixture和公开入口的停滞解码fixture同步提供该预检；原断言保留。真实BBDown公开入口测试继续使用外部假可执行文件和匿名HTTP响应，并更新预检使调用次数增加一次的断言。

新增`test_video_cache`在HTTP提交、真实worker、真实文件及维护CLI验证缓存。`NETWORK`只替换匿名元数据/HTTP边界，实际版本解析、传输大小/完整性核验、ffprobe、转换、schema与清理照常执行。覆盖强/弱ETag、命中/并发/取消、固定期限、在途预留、路径替换、半发布崩溃及新身份恢复；不把这些合成结果记作真实音乐校对。

配准的细黑边回归 `test_proven_thin_video_borders_do_not_join_all_printable_systems` 将至少两页的旧分页假设迁为 PDF 至少包含两个独立行组图片；紧凑排版可以一页容纳这些行组。原始谱区、长图逐像素和边缘彩色记号保留断言不变。


2026-10-26，#89 的自动主曲切片更新 `test_automatic_region_keeps_uncertain_single_late_staff_observation`：保留自动与手动谱区都能找出晚出现四行谱面的断言。旧的 blank/score/blank 必须 `discontinuity` 预期由实际四行交付和排除区间登记取代；多谱区歧义拒绝、失败不完整发布、全部采样来源及原位置重复保护继续由公开契约覆盖。
#90保留背景闪烁反例的原生变化大于1和零位移断言。实际seek补帧没有常规采样间隔运动摘要，最大值断言仅读取具有该摘要的采样，避免把新增真实补证帧当作常规采样。


## Issue #92 真实观测恢复

`test_gray_and_scrolling_watermarks_and_playback_effects_keep_source_pixels` 更名为 `test_proven_screen_overlays_restore_and_source_bound_marks_keep_pixels`。固定屏幕灰水印和移动窄竖光标的原像素恒等断言迁为同位置真实无遮挡原图恒等及非零恢复数，随谱水印、无覆盖物对照、最终位移、固定掩码和 `reliable=false` 断言保留。`test_observed_restoration` 另核验含真实音符的独立原图、每块精确来源像素与PTS/time_base，以及同色真实长竖记号不被擦除。没有删除测试。

本次成功光标夹具在视频外边缘内缩5像素。旧夹具的光标接触外边缘且首部没有无遮挡观测，#89的边缘保护会正确拒绝它，不能将该情形继续声明为完整谱面成功。固定水印测试加入黑场片头，以核验自动范围排除后恢复块仍指向完整原采样清单的正确索引和hash。


2026-10-26，#91 保留旧 `test_detected_page_flip_does_not_silently_publish_only_first_page` 的拒绝与不完整发布断言。该1fps案例缺少窗口内每侧两个稳定原生画面的页序证据，不能代表全部无重叠翻页必须拒绝。新增 `test_page_transitions` 经公开convert验证稳定硬切页序、20px残片的唯一完整观测替换、浅灰独有记号拒绝、回跳、短驻留页、微小独有黑记号、过渡动画及共享RGB预算耗尽。既有窄重叠、周期采样别名、原位置重复音乐与小节号细节反例继续运行，未删除测试。`test_native_page_order_and_continuity_agree_across_entries` 共同核对Python、CLI与真实HTTP worker结果语义。

#91 联合验证发现整合前置 `bcaa973` 的 `test_repeated_music_with_small_measure_numbers_retains_fast_scroll_positions` 已因 #90 新增原生变化峰帧而失败。保留7行和独立原图逐像素覆盖断言，将恰好六个placement的固定列表迁移为原六个常规位置全保留、首尾与顺序不变，允许必要原生见证带来额外正确位置。新增的独立RGB唯一候选核验使用真实局部小节号像素消歧，不执行OCR、猜测数字增量或运动先验；重复候选仍拒绝。

#93 保留 `test_preflight_keeps_uncertain_intro_and_checks_distributed_native_frames` 的分散观测、实际 PTS/time_base 和 continue 判定断言，将滚动末位移135改为90。旧夹具在画面底部截到下一行符干，按新增完整性保护应拒绝；改后的夹具用完整末行验证预检职责，未补全边缘的拒绝另由公开黑色及浅灰符干反例保护。

#93 审阅补充固定灰水印恢复夹具：原37像素步长的末尾853包含840/845/850三条残线，按完整行规则应拒绝。改为30像素步长，保留十个独立非零滚动视口、170至380行独立原图逐像素、恢复块RGB/PTS/time_base/hash、同色真实记号及全部产物断言，并增加至少三个成功覆盖物比较的断言。未删除测试。新的上下边缘各2/3/4条白边残组反例继续保护这类拒绝。


#93 最终并发回归保留原 `test_external_writer_does_not_abort_parallel_tasks_when_scheduler_poll_is_busy` 的两任务完成和worker退出断言，新增 `test_external_writer_during_stage_update_does_not_fail_running_tasks`，以真实SQLite外部写事务和阶段握手稳定触发一秒busy超时。未知阶段、完成和领取commit确认仍有独立真实worker反例，不把任意数据库错误归为可忽略进度。

父亡清理新增确定性公开CLI反例和guardian握手前失败反例，旧调用方强杀、PID复用、取消、期限与临时根清理断言保留。测试夹具先原子登记已知进程身份，外层确认后才允许暂停guardian；最终decoder marker缺失时也按原身份恢复和收尾。另在fork后、最终marker前注入故障，预期测试失败而清理断言通过，仅证明夹具异常收尾，不计产品通过。没有删除旧测试或放宽失败后的活动进程检查。


## 同列记号归属实验

2026-10-29，`test_staff_boundaries` 的模糊文字参数断言迁移到 `test_staff_ownership`：上行 mf 改为完整归上行的实际 PDF 断言；R R L 保留列间冲突拒绝，并新增疏排字母整组拒绝。旧模糊框、黑点、近邻文字、开镲圆圈近似等距、浅色组件、跨行连接、预算与像素保护断言继续保留。没有删除旧测试文件。实际 S12 错行说明合成通过仍不足以接受该实验算法，见同列归属实验记录。
