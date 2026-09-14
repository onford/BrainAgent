# 侵入式神经数据预处理

首版使用现有 `data_preprocessing` Agent、`PreprocessingService`、owner 隔离存储和证据工具，另设 modality-aware NWB adapter，避免 NWB 进入会 `preload=True` 的 BIDS-EEG reader。

## 已执行的范围

- 只读检查 `.nwb` 的 session/subject、Units、electrodes、ElectricalSeries/LFP、behavior、stimulus、trials、shape、dtype、unit、chunk、compression 与 timebase；Survey 只读取少量 scalar endpoint，不读取连续信号数组。
- 若存在 `Units/spike_times`，保留发布方 unit ID 并跳过 spike sorting；计算 firing rate、ISI violation、temporal presence/stability、non-finite/monotonicity 和发布方 quality，逐 unit 保存保留/删除理由。
- 检查 neural、behavior/stimulus 和 trial 的 timestamp 单调性、coverage、gap 与相对 offset。
- 可输出 `(unit_id, spike_time)` events、`T×N` binned/smoothed matrix、trial-start-aligned tensor 和数值 target；所有阈值、bin 和 smoothing 都是 plan 参数，不是唯一方法。
- 在存在数值 target 时运行 chronological 80/20 ridge diagnostic，并明确它不是科学有效性的证明。
- 输出 `manifest.json`、`preprocessing-config.json`、`provenance.json`、`qc-decisions.json`、`alignment.json`、`validation.json`、`report.md` 和模型数组。

FALCON M1 profile 会把 NWB `Units` 中按 array channel 保存的 multiunit threshold crossings 与 sorted single units 区分开：保留 64 路 channel identity，可规范化源事件顺序，但不使用只适用于单神经元的 refractory-period 阈值删除通道。`/acquisition/preprocessed_emg/*` 会组合成多通道 target，`eval_mask` 用作发布方定义的训练/评价 split。

若只有 raw voltage，Planner 会列出 filtering、artifact removal、referencing、spike detection/sorting 和 waveform/QC 候选步骤，但保持不可执行，直到已有文献/代码检索取得数据集或相似实验的官方方法，并提供固定的 probe/sorter/container profile 和代表性数据验证。首版识别 ophys metadata，但不执行 2-photon 数值重处理。

## API

先将 NWB 所在目录加入 `PREPROCESSING_INPUT_ROOTS`，然后调用：

1. `POST /api/preprocessing/invasive/inspect`：`{"path":"/absolute/session.nwb","hash_source":true}`
2. `POST /api/preprocessing/invasive/plans`：传入 `snapshot_ref`、任务、可选 `qc`/`transform`/证据 refs。
3. 仅当 plan 的 `executable=true` 时调用 `POST /api/preprocessing/invasive/runs`：`{"plan_ref":{...}}`。

运行返回 immutable `result_ref`；用 `GET /api/preprocessing/invasive/results/{id}` 查询结果，或用 `GET /api/preprocessing/invasive/results/{id}/artifacts/report.md` 下载报告。artifact 与结果查询均执行 owner 隔离和路径边界检查。

`hash_source=true` 会顺序计算整个文件的 SHA-256，适合正式可复现运行；超大文件可在初步 Survey 关闭，报告会明确 fingerprint 仅使用 size 和 modification time。输入文件始终只读，输出按 owner 与 immutable plan ref 隔离。
