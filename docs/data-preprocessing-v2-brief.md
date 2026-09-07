# Data Preprocess 简短介绍

Data Preprocess 负责对信息调研充分、且符合标准目录结构的 EEG 数据，生成并执行预处理流程。

模块由基本单元库、方法库、流程规划器和执行器组成。基本单元按《预处理基本单元》表实现；方法库统一接收专用子 Agent 调研的经典流程，以及 Data Survey 提供的文献方法。规划器根据数据与任务绑定参数，检查适用性、去重并开展探索性初筛；执行器运行入选流程，保存数据、参数、模型、处理决定、事件映射及状态，交给 Data Evaluation 比较质量和选择最佳结果。

[实现主方案](E:/work/BrainAgent/docs/data-preprocessing-v2-plan.md)
