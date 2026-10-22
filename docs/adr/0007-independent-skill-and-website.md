---
status: accepted
---

# 同一仓库中的独立 Skill 和网站

2026-10-22，用户明确要求保留原仓库作为统一入口，main 同时提供 Skill 和网站，两者独立，提交 PR。该决定替代 [ADR 0006](0006-script-product-lifecycle.md) 中删除 Skill 分发、专属入口与测试的范围决定；网站本身的转换与生命周期契约保持不变。

## 边界

| 路径 | 负责的产品 | 发布和验证 |
| --- | --- | --- |
| `skills/bilibili-drum-score-to-pdf/` | 自包含 Skill、脚本与便携协议 | 安装整个目录，使用其中的 requirements；`tests/skill/` 和 `skill.yml` 独立验证。 |
| `src/drum_score/` | 纯程序核心、CLI、可选网站与 worker | `pyproject.toml` 构建 wheel；根 `tests/test_*.py` 和 `offline.yml` 验证。 |
| `tools/install_skill.py`、`tools/sync_skill_references.py` | Skill 提交快照安装、恢复及协议同步 | 不安装网站，不修改已安装宿主配置。 |
| 根 README、`docs/README.md` | 统一导航 | 分别指向两条安装、使用与验证路径。 |

Skill 恢复远端 main 提交 `b4be2dc44427c3e0a7c741c7d1f81e23a41b6d2b` 的完整包，保留该产品原有行为与固定依赖，包括自己的匿名获取实现。网站保持已验证的 BBDownNext 2.3.0 直连入口，不把 Skill 的 yt-dlp 依赖加入网站安装。

两者不互相 import、不发起相互服务调用、不合并队列、状态、输出目录或审核语义。相似的网络与视频工具保留在各自产品内，避免一次接口变更同时影响两种生命周期。共享仓库许可证、文档入口和无产品状态的 CI 工具，不建立第三层通用运行时。

## 验证与代价

两套 CI 使用各自的独立依赖环境与测试目录，分别重放合成输入。Skill 继续验证脱离仓库的分发包；程序另验证脱离 Skill 和仓库工具的转换。安装包核对 wheel 不含 Skill，Skill 提交快照不含网站。

代价是相似工具存在两个实现，安全修复需要分别评估和运行对应契约。当前不重构共享核心，也不改变生产部署或现有用户安装。历史迁移表只说明 #73 当时从 Skill 到网站的处理，不再代表 Skill 功能被全仓库删除。

该改动可通过撤回 PR 还原仓库布局。合并本身不部署服务、不改变数据库、不迁移任务；服务器回滚仍按网站部署指南执行。
