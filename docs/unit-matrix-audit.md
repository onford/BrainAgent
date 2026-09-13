# 配置矩阵的本轮核验

当前目录包含54单元、91操作、310配置。历史306配置的来源一致性记录和11项真实EEG记录保留各自的引擎版本，不能直接补入新版本的通过计数。

完成数值运行后，用该运行的冻结环境与应用源码执行汇总审计。`--validation-script`必须指向独立确认的冻结验证脚本；不要从结果回执中复制一个未经核对的哈希作为信任依据。

```powershell
python -m scripts.audit_unit_matrix `
  --profiles <本轮profiles目录> `
  --validation-script <冻结副本/backend/scripts/validate_units_v2.py> `
  --output <新的独立审计目录>
```

审计核对完整配置分母、结果索引与逐项回执的一致性、源码/引擎/环境与验证脚本版本，以及产物的路径、字节数和哈希。全部读取文件在结束时再次核对。重复、越界、缺失或不一致证据直接拒绝；正常失败与未执行配置保留在矩阵中。

输出包括`audit.json`、`matrix.md`和供复核的`verification_v2.json`。审计不会修改服务注册表；只有全部配置通过才将审计状态记为passed，其他有效但不完整的结果为partial。真实EEG字段在此来源一致性审计中保持false；额外真实数据回执必须单独核验。

常规配置采用固定合成输入。完整原生流程通过`validate_units_v2`的`--native-input`、`--native-record`、`--native-bindings`显式指定真实记录和资产；辅助脚本版本也写入并核对回执。PREP、Automagic、RELAX比较完整数据、MNE状态、诊断和解码后的MAT内容，仅归一化MAT文件头时间戳和临时工作目录名称，原始容器分别无损留存。作者时钟随机配置若实际不一致会保留为失败，不放宽数值容差以声称确定性复现。

这些对比是适配一致性证据，不证明作者算法科学正确、真实神经活动得到保护或最终agent已通过验收。本汇总器仍不直接发布真实EEG覆盖声明；真实数据回执需要另行核验。

MATLAB v7.3中间容器按HDF5内容读取，保留数据集、属性、维度和对象引用目标；MATLAB字符向量仅按同一临时路径规则归一化。对象引用先建立地址到路径索引，避免对大型引用表反复遍历。未支持的区域引用、外部链接和循环组明确失败。实现依据见[h5py对象引用文档](https://docs.h5py.org/en/stable/refs.html)与[文件对象文档](https://docs.h5py.org/en/stable/high/file.html)。不改变数据容差，不抹去诊断或处理时长。

真实原生回执完成后，另行运行只读复核（使用同一冻结应用/环境，以及哈希一致的原生辅助脚本）：

```powershell
python <审核工具/backend/scripts/audit_native_profile_evidence.py> `
  --profiles <已完成的profiles目录> `
  --validation-script <冻结副本/backend/scripts/validate_units_v2.py> `
  --input <原始PreprocessInput.json> --record S001R04 `
  --bindings <原始native-bindings.json> --output <新的独立审计目录>
```

工具先运行完整分母的矩阵审计，再核对明确指定的真实记录、配方和依赖；重新加载直接来源与图执行的完整描述及容器，从原始事件重建保留试次映射，对照输入/输出哈希及执行日志。结束时再次检查读取的证据、原始数据、原生依赖、引擎和环境。缺少直接来源描述的旧运行不能靠猜测文件名补成通过。失败和未执行配置保留，结果写入`native-audit.json`，不直接更改服务注册表。单条真实记录的一致性不代表全部真实数据覆盖或科学效用。
