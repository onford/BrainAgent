# EEGMMIDB 全集资源测量

本项测量保留 109 名参与者、327 条运动想象记录和 4918 个试次。所有记录执行同一配方；参与者编号只用于分组外折和统计。冻结五折、种子 17/42/2026、EEGNet 最大 100 epochs、patience 15 和 batch size 64，不以减少参与者或训练次数控制成本。

## 测量入口

`backend/scripts/profile_search_cost.py` 接受经过验证的完整 Collection `input.json` 和一个新输出目录。它执行基础候选的预处理、CSP 锚点、完整效用评价、质量评价和重建评价。输入范围不足或输入/输出目录重叠时拒绝开始。源码、原始输入清单和驱动均记录哈希；缺少完整评价或发生变动时返回非零退出码。

这是一项工程资源测量，直接提供已知 Collection 上下文，不包含上游文献调研，也不能替代正式 agent 验收。

在冻结的 backend 副本中运行，例如：

```powershell
python scripts/profile_search_cost.py --input-json E:/verified-collection/input.json --output E:/new-cost-run --seconds 14400 --memory-mb 16384 --disk-mb 65536
```

这里的四小时是可供新测量声明的操作预算，不是实测完成时间。已开始运行的截止时间和预算保持不变。

## 计量范围

- Windows Job 的 CPU 用户/内核时间和 I/O transfer 计数包含已退出的子进程。采样周期为 0.25 秒，进程树 RSS 是采样最大值，共享映射可能重复计入。
- transfer bytes 包含缓存等 I/O，不表示物理磁盘流量。CPU 时间可跨进程累加；墙钟减 CPU 不是 I/O 等待。
- 独立图执行探针尝试开启 Job storage attribution，保留队列、服务和字节原始计数；未确认时间单位时不转换成秒。主线程 cProfile 的累计时间相互重叠，不能相加；其开销计入测量。
- 图探针仅测共享图执行、检查点和保存，并逐记录比较最终物理数组；它不产生新的 15 次 EEGNet 训练。图成本与完整候选成本分别报告。

新评价在 `_assessment/stage-resources/` 保存效用、质量、重建的独立起止时间、墙钟和当前评价进程 CPU 时间；这些文件纳入产物清单和哈希验证。`returned` 仅指函数返回，不能替代科学评价状态；异常记为 `raised`，强制退出而未写出文件的阶段保持缺测。该 CPU 字段明确不包含效用或原生子进程，需结合它们的回执及外部 Job 计数。观测代码不改变模型、输入范围或资源限额。

计数依据：[Microsoft Job CPU accounting](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_basic_accounting_information)、[I/O counters](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-io_counters)、[Microsoft hcsshim storage attribution](https://github.com/microsoft/hcsshim/blob/main/internal/jobobject/jobobject.go)。纯进程 I/O 等待目前标记为未测得。

## 当前运行

2026-09-13 的 `full-cost-1` 在原定 7200 秒预算内结束，停止原因是候选数已用完，未延长截止时间。15 次 EEGNet 训练、全部质量检查和重建适用性检查均已执行；输入与冻结代码哈希不变。详见 [独立成本复核](sources/remaining-modifications-20260912/full-cost-1-review.json)。

| 观测 | 结果 |
| --- | --- |
| 搜索执行及关闭阶段墙钟 | 6995.450 秒，116.591 分钟 |
| 基础配方预处理 | 627.947 秒，4 个记录工作进程 |
| 评价及其核查合计 | 6322.385 秒 |
| EEGNet 工作进程 | 墙钟 4154.906 秒，CPU 4098.563 秒；15 次训练共 438 epochs |
| CSP/LDA 效用工作进程 | 墙钟 2.750 秒，CPU 0.938 秒 |
| 重建阶段内部计时 | 88.753 秒 |
| 候选 Job CPU | 用户 5184.000 秒，内核 1229.672 秒 |
| 外部 0.25 秒采样 RSS 最大值 | 4169105408 字节；控制器另观察到 4266209280 字节，均不是连续测得的绝对峰值 |
| 候选 Job transfer bytes | 读取 208950082811，写入 15845072480；不是物理磁盘流量 |
| 搜索目录大小 | 15.612 GiB；不含既有完整 BIDS 输入及目录外文件 |

质量检查覆盖全部 109 人、327 记录、4918 试次，缺失试次为 0。重建检查了 109 个分配案例：92 可评价、17 个脉冲案例不适用；部分冻结试次的 cleanproxy 或共同频带注入量不足，原分母和阈值均保留。重建实际完成 109 次 clean replay、92 次 corrupted replay。因此三轴科学回执仍为 `partial`，不能把该运行解释为重建覆盖全部通过，也不能把此成本当作 109 个全部适用案例的完整重放成本。资源驱动分别提供 `execution_finished`、`assessment_statuses` 和保守的 `measurement_complete`；科学评价不完整时仍返回非零，避免把过程结束误报为全项通过。

旧冻结代码没有单独的质量起止计时；总评价时间还包括装配、序列化和验签，不能直接把减去已知子阶段后的差值称为纯质量耗时。新阶段观测用于后续运行，不反填旧记录。

共享 v2 图探针已完成：327 条记录/109 人，执行 2482.143 秒、全数组验签比较 138.727 秒，最大绝对差 **0 V**，原数据和冻结代码不变。输出 30297456930 字节（约 28.217 GiB），Job CPU 用户 729.875 秒、内核 769.734 秒，采样 RSS 最大 783736832 字节。详见 [图组件复核](sources/remaining-modifications-20260912/graph-cost-1-review.json)。基础配方采用 4 个记录进程，而当前 v2 图逐记录执行并含 cProfile 开销，两者墙钟差异不能全部归因于存储格式。

主线程剖析观测到 5559 次 `fsync`，累计调用墙钟 529.508 秒，属于值得进一步优化的持久化成本；它不是整个进程的纯 I/O 等待。Job storage attribution 成功取得原始队列/服务计数，未确认单位，保持未转换。不得通过删除崩溃恢复所需的持久化保证来消除这些成本。

据此次共享主机实测，下一次全集搜索宜顺序评价候选，继续保持完整五折/三种子和数值默认值。普通共享图候选可先按约 2–3 小时/个规划，四候选约 8–12 小时；这是结合组件测量的预算估计，不是四候选实测，也不适用于任意原生复杂方法。建议新搜索事先声明 12 小时、16 GiB 进程树内存、256 GiB 目录上限，模型总时限另留上游调研与交付余量。17 个不适用重建案例仍需在正式流程前解释其对完整性门槛的影响，不能凭预算充足就宣布可验收。

主机为 Intel Core Ultra 7 265（20 核/20 逻辑处理器）、68135153664 字节物理内存、Windows 11 build 26200；Python 3.12.14、torch 2.8.0+cpu、NumPy 1.26.4、SciPy 1.15.3、MNE 1.10.2。本次效用实际并发为 1（冻结允许上限为 2，由 16 GiB 总预算下的单模型内存预留约束），BLAS/Torch 线程为 1。测量期间存在同机目录检索及短时专项回归，原始备注保留；这些结果不是空闲主机基准。

正式验收驱动 `backend/scripts/release_workflow_acceptance.py` 已区分实际 109 人范围与声明面板，记录数据集级元数据、文件增删、全部应用文件和驱动哈希。正式流程仍需独立创建、fresh 调研和真实来源候选参与；这项驱动修正不提升任何历史失败运行的验收状态。

工作流请求可通过 `model_budget_seconds`（驱动参数 `--model-budget-seconds`）事前声明模型请求总时限，默认仍为 21600 秒，允许 1–604800 秒。新工作流创建时写入绝对截止时间，数值计算和排队等待均计时；恢复或重试不会重新开始计时。128 次请求、累计输入及输出预留等原有限额不变。全集数值搜索的时间预算与模型请求时限分别冻结和展示于原始请求/预算文件，不能在运行中延长任一限额。
