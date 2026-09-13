# 保存模型与物理数组核验

`backend/scripts/audit_eegnet_checkpoints.py` 只读核验已有候选，不重新训练模型，也不将未通过的候选变为最终选择。输出必须是搜索目录之外的新目录。

从项目根目录运行：

```powershell
$env:PYTHONPATH = "$PWD/backend"
& backend/.venv-eeg/Scripts/python.exe backend/scripts/audit_eegnet_checkpoints.py --candidate <搜索目录>/candidates/<候选ID> --output <新的核验目录>
```

核验范围：

- 对照搜索快照、评估绑定、计划及完整面板哈希；保留每个实际读取文件的校验和。
- 将每一效用输入行与保存的物理电压、事件ID、源样点、标签及epoch位置逐一比较。
- 重建冻结的训练/验证被试划分，只从内部训练试次重新计算通道均值和标准差，比较检查点中的统计量。
- 用保存的权重推理全部五折、三个种子，复核逐试次概率与标签、逐被试平衡准确率和三个种子的宏平均分数。每折完成后单独写核验结果。
- 结束后再次核对所有读取文件；不完整、文件变动、路径越界或校验和不同均拒绝通过。

核验使用已登记且与冻结协议哈希一致的网络结构；推理、数组关联和统计复算独立于生产预测/装配函数。它不是另一套网络实现或独立测试集实验，不证明原始EEG的神经真值。最终候选交付还须单独核对ZIP、导出数组、事件索引、路径可迁移性和训练示例。

首次完整实测使用历史 `bp8-30-average` 基线：109人、327记录、4918试次、15模型，最大概率差约1.11e-16；708个读取文件结束后哈希不变，复算开发分数0.6395565759876151。原候选的三轴状态仍为 `partial`。见 [核验回执](sources/remaining-modifications-20260912/eegnet-checkpoint-audit.json)。这仅为I43后续正式交付核验的工具准备，未完成新赢家交付验收。

`backend/scripts/audit_training_archive.py` 核对交付ZIP与发布清单、选中回执、物理数组和冻结事件，并在新目录解压便携入口。它逐成员验证大小和哈希，拒绝路径越界、符号链接及重复成员；导出float32数组与原始物理V数组的对应转换逐值一致才通过。

```powershell
& backend/.venv-eeg/Scripts/python.exe backend/scripts/audit_training_archive.py --workflow <工作流目录> --search <搜索目录> --output <新的核验目录> --run-example --template-sha256 <可信冻结源码中训练模板的SHA256>
```

训练示例仅在与独立可信模板哈希一致后运行，使用新解压目录，不写入历史运行。该示例检查文件与训练接口兼容性，不评价模型质量。实际保存的EEGNet预测由上面的检查点工具另行复核。

历史第8次交付包的4人、12记录、180试次、157个ZIP成员通过检查，训练示例实际运行成功，31个读取文件保持不变，用时9.110秒。错配模板与越界ZIP两个反向控制均被拒绝，原始ZIP不变。见 [交付包核验回执](sources/remaining-modifications-20260912/training-archive-audit.json)。第8次实质文献验收仍为失败；这次核验不替代新赢家的正式验收。
