---
status: accepted
---

# 单调度器管理有界并行转换

2026-10-23，用户确认不同 IP 最多八路转换、同 IP 一个未完成任务、预算优先及短暂维护的需求。网站保留单机唯一调度器与全局锁，以有界监督线程调用已有独立转换进程。多个独立 worker 需要重新分配启动恢复、暂存清理及维护锁的所有权；当前规模不引入分布式队列或第二套状态服务。

每个监督线程显式绑定任务上下文和 guardian 租约；全部监督线程及 guardian 停止后才释放服务锁。调度器主线程统一接收信号，通过 `Event` 通知监督循环取消，线程池仅执行有限时单次任务，不承担额外持久队列。数据库领取事务限制名额并为活动任务保守预留临时空间。源码默认一路，配置最多八路，生产开放数量须通过目标机验收。

移除单活动唯一索引需要 schema v2。程序启动拒绝自动升级；专用 `upgrade-v1` 核验旧快照、复制到新目录、升级副本并登记新文件身份。代价是旧程序不能读取新库，回滚必须匹配保留的旧发行和旧数据根。旧备份、未到期结果和原期限不变。

线程与信号语义依据 [Python 3.12 信号文档](https://docs.python.org/3.12/library/signal.html#signals-and-threads)、[ContextVar](https://docs.python.org/3.12/library/contextvars.html#contextvars.Context) 和 [spawn](https://docs.python.org/3.12/library/multiprocessing.html#contexts-and-start-methods)。[线程池文档](https://docs.python.org/3.12/library/concurrent.futures.html#concurrent.futures.ThreadPoolExecutor) 提醒异常退出时不能依赖退出钩子停止任务，因此主线程所有退出路径先设置停止事件，再等待线程池，最后关闭租约。[SQLite](https://www.sqlite.org/lang_transaction.html) 仍仅允许一个写事务；监督线程不共享 connection，同一调度器内的短事务以本地锁协调，状态与取消轮询使用只读事务。清理或领取轮询忙时重试，不把线程数视为数据库写入并行度。
