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

计数依据：[Microsoft Job CPU accounting](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_basic_accounting_information)、[I/O counters](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-io_counters)、[Microsoft hcsshim storage attribution](https://github.com/microsoft/hcsshim/blob/main/internal/jobobject/jobobject.go)。纯进程 I/O 等待目前标记为未测得。

## 当前运行

2026-09-13 的 `full-cost-1` 在独立冻结副本上运行，原定总预算为 7200 秒。15 次 EEGNet 训练已完成，效用进程记录约 4160.875 秒；质量和重建评价尚未全部完成，因此目前没有完整候选成本结论。若触及原定预算，将保留失败产物，在新目录声明新预算，不能延长旧运行。

主机为 Intel Core Ultra 7 265（20 核/20 逻辑处理器）、68135153664 字节物理内存、Windows 11 build 26200；Python 3.12.14、torch 2.8.0+cpu、NumPy 1.26.4、SciPy 1.15.3、MNE 1.10.2。效用模型进程上限为 1，BLAS/Torch 线程为 1。测量期间存在同机目录检索及短时专项回归，原始备注保留；这些结果不是空闲主机基准。

正式验收驱动 `backend/scripts/release_workflow_acceptance.py` 已区分实际 109 人范围与声明面板，记录数据集级元数据、文件增删、全部应用文件和驱动哈希。正式流程仍需独立创建、fresh 调研和真实来源候选参与；这项驱动修正不提升任何历史失败运行的验收状态。
