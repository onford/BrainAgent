# 预处理全量接入验收结果

当前执行器 SHA-256：`bac7c8274b13b95763a1138e1185dbb54d7cc5fd412b03e1e088e8f23b858258`。首次冻结清单的全部 130 个身份保留，新增条目和合同修正见 inventory-amendment-final.json。

| 检查 | 实际结果 |
|---|---|
| 当前源码单元 / op / profile | 52 / 88 / 306 |
| 逐 profile 编译 / 运行 / 数值 / 边界 | 306 / 306 / 306 / 306 |
| 真实 EEG 覆盖的 profile | 11 |
| 补充组合与输入边界 | 188 / 188，其中数值运行 106、预期拒绝 82 |
| 后端回归 | 132 通过，失败 0、错误 0、跳过 0 |
| 前端测试 | 5 / 5；vue-tsc 与 Vite 构建通过 |
| 实际浏览器 | 306 条能力显示；编译并执行 2 条记录；下载 axes/provenance 并保存哈希 |

## 全量交付

- [全部单元 × op × profile 矩阵和参数合同](E:/work/BrainAgent/docs/sources/full-unit-integration-20260912/matrix.md)
- [机器可读完整矩阵、来源与输入输出](E:/work/BrainAgent/docs/sources/full-unit-integration-20260912/matrix.json)
- [逐项运行收据及补充组合收据](E:/work/BrainAgent/docs/sources/full-unit-integration-20260912/final-receipt-index.json)
- [真实运行的完整 MethodSpec](E:/work/BrainAgent/docs/sources/full-unit-integration-20260912/representative-methods.json)
- [逐记录参数已绑定的 ExecutionPlan](E:/work/BrainAgent/docs/sources/full-unit-integration-20260912/representative-execution-plan.json)
- [架构、使用、依赖及兼容说明](E:/work/BrainAgent/docs/preprocessing-integration-v2.md)
- [本验收摘要及证据文件哈希](E:/work/BrainAgent/docs/sources/full-unit-integration-20260912/acceptance.json)
- [实际 Edge 操作、下载与截图收据](E:/work/BrainAgent/.local/units-v2-audit/browser-final/browser-receipt.json)

## 实际流程

EEGMMIDB S001R04/S001R08：平均参考 → 1–40 Hz IIR → PICARD 拟合分支 → muscle slope 诊断 → 明确接受候选 → ICA 应用 → Epoch → baseline。另一配方使用 nanmedian 参考估计/应用模型、8–30 Hz Butterworth 和 window MAD 诊断分支。共 4 个结果，各 15 × 64 × 321，保存、回读、事件/Trial 映射及原始文件哈希检查通过。

另有 ICLabel → 眼动掩码 → eye weights → targeted WICA，以及 ADJUST/FASTER → SASICA → 待决定/确认 → ICA apply 的完整合成数据分支收据。回归基线的零、一、二因素输入、训练边界及两种数据表示分别验证；连续参数不按无穷笛卡尔积声称覆盖。

## 限制与未解决项

- 真实 EEG 只运行两个记录、两套配方；其余 profile 不标记真实数据验证通过。
- 数值验证检验冻结来源函数与图适配器一致性，另有状态/泄漏/绑定/边界测试；未独立复现所有作者论文实验。
- 来源批处理拟合器拒绝 subject_unlabeled/online，不静默转成 record_unlabeled。
- train/calibration 分区重放支持确定性前处理，尚不支持依赖上游模型、人工决定或外部参数端口的状态化重放。
- v2 有界图搜索可发现、选择、编译和执行候选；未接入旧 EEGNet 固定面板的评分、Trial 对齐与统一排名。
- 取消在步骤边界生效，原生算法调用尚无逐调用即时取消；实际作者运行时仍受其 timeout 控制。
- 方法提取已接入全量合同并通过入口测试；没有进行已配置外部语言模型的全量文献提取验收。

本机所需原生运行时、作者代码及模型资产已实际安装和验证，没有以缺资产条目冒充运行通过。后续机器必须按锁文件及固定来源部署；前端会根据当前环境显示依赖缺失。前期失败与被后续实现取代的运行目录均保留，最终成功率只使用当前执行器哈希的证据。

## 界面实测截图

![全量能力与参数编排](E:/work/BrainAgent/.local/units-v2-audit/browser-final/catalogue.png)

![编译、执行和结果](E:/work/BrainAgent/.local/units-v2-audit/browser-final/execution.png)
