# BrainAgent 全量单元接入与验证矩阵

当前源码：52 单元 / 88 op / 306 profile；原始 130 个身份全部保留。

编译 306，运行 306，来源数值一致性 306，边界行为 306，真实数据覆盖 11。

数值证据指独立调用冻结来源函数与图适配器结果的逐元素/模型/诊断比较及无损回读，不代表对作者算法的独立科学验证。真实数据列仅对应收据中的具体参数及记录。

[完整机器可读合同、输入输出、来源、依赖和验证收据](E:/work/BrainAgent/docs/sources/section-a-verification-20260912/matrix.json)

| 单元 | op | profile（完整身份） | 编译 | 运行 | 数值 | 边界 | 真实 EEG | 收据 |
|---|---|---|---|---|---|---|---|---|
| EEG-CROP | crop | source | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/000-crop/receipt.json) |
| EEG-CROP | crop_join | source | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/001-crop_join/receipt.json) |
| EEG-DETREND | detrend | type=constant | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/002-detrend/receipt.json) |
| EEG-DETREND | detrend | type=linear | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/003-detrend/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=zero,annotation_policy=raw | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/004-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=zero,annotation_policy=array | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/005-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=zero-double,annotation_policy=raw | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/006-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=zero-double,annotation_policy=array | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/007-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=minimum,annotation_policy=raw | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/008-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=minimum,annotation_policy=array | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/009-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=minimum-half,annotation_policy=raw | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/010-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=minimum-half,annotation_policy=array | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/011-filter/receipt.json) |
| EEG-FILTER | filter | method=iir,phase=zero,annotation_policy=raw | 通过 | 通过 | 通过 | 通过 | 通过 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/012-filter/receipt.json) |
| EEG-FILTER | filter | method=iir,phase=zero,annotation_policy=array | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/013-filter/receipt.json) |
| EEG-FILTER | filter | method=iir,phase=forward,annotation_policy=raw | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/014-filter/receipt.json) |
| EEG-FILTER | filter | method=iir,phase=forward,annotation_policy=array | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/015-filter/receipt.json) |
| EEG-FILTER | filter | method=iir,phase=zero-double,annotation_policy=raw | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/016-filter/receipt.json) |
| EEG-FILTER | filter | method=iir,phase=zero-double,annotation_policy=array | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/017-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=zero,annotation_policy=raw,fir_design=firwin,fir_window=hann | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/018-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=zero,annotation_policy=array,fir_design=firwin,fir_window=hann | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/019-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=zero,annotation_policy=raw,fir_design=firwin,fir_window=blackman | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/020-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=zero,annotation_policy=array,fir_design=firwin,fir_window=blackman | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/021-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=zero,annotation_policy=raw,fir_design=firwin2,fir_window=hamming | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/022-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=zero,annotation_policy=array,fir_design=firwin2,fir_window=hamming | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/023-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=zero,annotation_policy=raw,fir_design=firwin2,fir_window=hann | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/024-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=zero,annotation_policy=array,fir_design=firwin2,fir_window=hann | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/025-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=zero,annotation_policy=raw,fir_design=firwin2,fir_window=blackman | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/026-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=zero,annotation_policy=array,fir_design=firwin2,fir_window=blackman | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/027-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=zero-double,annotation_policy=raw,fir_design=firwin,fir_window=hann | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/028-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=zero-double,annotation_policy=array,fir_design=firwin,fir_window=hann | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/029-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=zero-double,annotation_policy=raw,fir_design=firwin,fir_window=blackman | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/030-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=zero-double,annotation_policy=array,fir_design=firwin,fir_window=blackman | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/031-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=zero-double,annotation_policy=raw,fir_design=firwin2,fir_window=hamming | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/032-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=zero-double,annotation_policy=array,fir_design=firwin2,fir_window=hamming | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/033-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=zero-double,annotation_policy=raw,fir_design=firwin2,fir_window=hann | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/034-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=zero-double,annotation_policy=array,fir_design=firwin2,fir_window=hann | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/035-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=zero-double,annotation_policy=raw,fir_design=firwin2,fir_window=blackman | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/036-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=zero-double,annotation_policy=array,fir_design=firwin2,fir_window=blackman | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/037-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=minimum,annotation_policy=raw,fir_design=firwin,fir_window=hann | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/038-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=minimum,annotation_policy=array,fir_design=firwin,fir_window=hann | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/039-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=minimum,annotation_policy=raw,fir_design=firwin,fir_window=blackman | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/040-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=minimum,annotation_policy=array,fir_design=firwin,fir_window=blackman | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/041-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=minimum,annotation_policy=raw,fir_design=firwin2,fir_window=hamming | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/042-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=minimum,annotation_policy=array,fir_design=firwin2,fir_window=hamming | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/043-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=minimum,annotation_policy=raw,fir_design=firwin2,fir_window=hann | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/044-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=minimum,annotation_policy=array,fir_design=firwin2,fir_window=hann | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/045-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=minimum,annotation_policy=raw,fir_design=firwin2,fir_window=blackman | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/046-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=minimum,annotation_policy=array,fir_design=firwin2,fir_window=blackman | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/047-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=minimum-half,annotation_policy=raw,fir_design=firwin,fir_window=hann | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/048-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=minimum-half,annotation_policy=array,fir_design=firwin,fir_window=hann | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/049-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=minimum-half,annotation_policy=raw,fir_design=firwin,fir_window=blackman | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/050-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=minimum-half,annotation_policy=array,fir_design=firwin,fir_window=blackman | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/051-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=minimum-half,annotation_policy=raw,fir_design=firwin2,fir_window=hamming | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/052-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=minimum-half,annotation_policy=array,fir_design=firwin2,fir_window=hamming | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/053-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=minimum-half,annotation_policy=raw,fir_design=firwin2,fir_window=hann | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/054-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=minimum-half,annotation_policy=array,fir_design=firwin2,fir_window=hann | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/055-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=minimum-half,annotation_policy=raw,fir_design=firwin2,fir_window=blackman | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/056-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=minimum-half,annotation_policy=array,fir_design=firwin2,fir_window=blackman | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/057-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=zero,annotation_policy=array,nonfinite=propagate | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/058-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=zero-double,annotation_policy=array,nonfinite=propagate | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/059-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=minimum,annotation_policy=array,nonfinite=propagate | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/060-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=minimum-half,annotation_policy=array,nonfinite=propagate | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/061-filter/receipt.json) |
| EEG-FILTER | filter | method=iir,phase=zero,annotation_policy=array,nonfinite=propagate | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/062-filter/receipt.json) |
| EEG-FILTER | filter | method=iir,phase=forward,annotation_policy=array,nonfinite=propagate | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/063-filter/receipt.json) |
| EEG-FILTER | filter | method=iir,phase=zero-double,annotation_policy=array,nonfinite=propagate | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/064-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=zero,annotation_policy=array,fir_design=firwin,fir_window=hann,nonfinite=propagate | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/065-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=zero,annotation_policy=array,fir_design=firwin,fir_window=blackman,nonfinite=propagate | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/066-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=zero,annotation_policy=array,fir_design=firwin2,fir_window=hamming,nonfinite=propagate | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/067-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=zero,annotation_policy=array,fir_design=firwin2,fir_window=hann,nonfinite=propagate | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/068-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=zero,annotation_policy=array,fir_design=firwin2,fir_window=blackman,nonfinite=propagate | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/069-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=zero-double,annotation_policy=array,fir_design=firwin,fir_window=hann,nonfinite=propagate | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/070-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=zero-double,annotation_policy=array,fir_design=firwin,fir_window=blackman,nonfinite=propagate | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/071-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=zero-double,annotation_policy=array,fir_design=firwin2,fir_window=hamming,nonfinite=propagate | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/072-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=zero-double,annotation_policy=array,fir_design=firwin2,fir_window=hann,nonfinite=propagate | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/073-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=zero-double,annotation_policy=array,fir_design=firwin2,fir_window=blackman,nonfinite=propagate | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/074-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=minimum,annotation_policy=array,fir_design=firwin,fir_window=hann,nonfinite=propagate | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/075-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=minimum,annotation_policy=array,fir_design=firwin,fir_window=blackman,nonfinite=propagate | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/076-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=minimum,annotation_policy=array,fir_design=firwin2,fir_window=hamming,nonfinite=propagate | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/077-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=minimum,annotation_policy=array,fir_design=firwin2,fir_window=hann,nonfinite=propagate | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/078-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=minimum,annotation_policy=array,fir_design=firwin2,fir_window=blackman,nonfinite=propagate | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/079-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=minimum-half,annotation_policy=array,fir_design=firwin,fir_window=hann,nonfinite=propagate | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/080-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=minimum-half,annotation_policy=array,fir_design=firwin,fir_window=blackman,nonfinite=propagate | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/081-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=minimum-half,annotation_policy=array,fir_design=firwin2,fir_window=hamming,nonfinite=propagate | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/082-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=minimum-half,annotation_policy=array,fir_design=firwin2,fir_window=hann,nonfinite=propagate | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/083-filter/receipt.json) |
| EEG-FILTER | filter | method=fir,phase=minimum-half,annotation_policy=array,fir_design=firwin2,fir_window=blackman,nonfinite=propagate | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/084-filter/receipt.json) |
| EEG-FILTER | butter | kind=highpass,phase=zero | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/085-butter/receipt.json) |
| EEG-FILTER | butter | kind=highpass,phase=forward | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/086-butter/receipt.json) |
| EEG-FILTER | butter | kind=lowpass,phase=zero | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/087-butter/receipt.json) |
| EEG-FILTER | butter | kind=lowpass,phase=forward | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/088-butter/receipt.json) |
| EEG-FILTER | butter | kind=bandpass,phase=zero | 通过 | 通过 | 通过 | 通过 | 通过 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/089-butter/receipt.json) |
| EEG-FILTER | butter | kind=bandpass,phase=forward | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/090-butter/receipt.json) |
| EEG-FILTER | butter | kind=bandstop,phase=zero | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/091-butter/receipt.json) |
| EEG-FILTER | butter | kind=bandstop,phase=forward | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/092-butter/receipt.json) |
| EEG-FILTER | notch | source | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/093-notch/receipt.json) |
| EEG-SINE-REGRESSION | spectrum_fit | source | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/094-spectrum_fit/receipt.json) |
| EEG-SINE-REGRESSION | spectrum_fit | nonfinite=propagate | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/095-spectrum_fit/receipt.json) |
| EEG-SINE-REGRESSION | cleanline | source | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/096-cleanline/receipt.json) |
| EEG-SINE-REGRESSION | cleanline | scan_bandwidth=2.0 | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/097-cleanline/receipt.json) |
| EEG-RESAMPLE | resample | source | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/098-resample/receipt.json) |
| EEG-RESAMPLE | resample_fft | source | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/099-resample_fft/receipt.json) |
| EEG-RESAMPLE | resample_fir | source | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/100-resample_fir/receipt.json) |
| EEG-RESAMPLE | resample_eeglab | source | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/101-resample_eeglab/receipt.json) |
| EEG-RESAMPLE | decimate | source | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/102-decimate/receipt.json) |
| EEG-REREFERENCE | reference | source | 通过 | 通过 | 通过 | 通过 | 通过 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/103-reference/receipt.json) |
| EEG-REREFERENCE | reference | ref_channels=['Cz'] | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/104-reference/receipt.json) |
| EEG-REREFERENCE | reference | ref_channels=['C3', 'C4'] | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/105-reference/receipt.json) |
| EEG-REREFERENCE | relax_car | source | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/106-relax_car/receipt.json) |
| EEG-REREFERENCE | reference_estimate | estimator=nanmean | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/107-reference_estimate/receipt.json) |
| EEG-REREFERENCE | reference_estimate | estimator=nanmedian | 通过 | 通过 | 通过 | 通过 | 通过 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/108-reference_estimate/receipt.json) |
| EEG-REREFERENCE | reference_estimate | estimator=nanmean,nonfinite=propagate | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/109-reference_estimate/receipt.json) |
| EEG-REREFERENCE | reference_estimate | estimator=nanmedian,nonfinite=propagate | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/110-reference_estimate/receipt.json) |
| EEG-REREFERENCE | reference_apply | source | 通过 | 通过 | 通过 | 通过 | 通过 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/111-reference_apply/receipt.json) |
| EEG-REREFERENCE | reference_apply | nonfinite=propagate | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/112-reference_apply/receipt.json) |
| EEG-REST | rest | source | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/113-rest/receipt.json) |
| EEG-CSD | csd | source | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/114-csd/receipt.json) |
| EEG-BAD-CHANNEL-LOF | lof_detect | source | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/115-lof_detect/receipt.json) |
| EEG-AMPLITUDE-THRESHOLD | amplitude_detect | source | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/116-amplitude_detect/receipt.json) |
| EEG-AMPLITUDE-THRESHOLD | flat_detect | source | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/117-flat_detect/receipt.json) |
| EEG-AMPLITUDE-THRESHOLD | amplitude_windows | source | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/118-amplitude_windows/receipt.json) |
| EEG-AMPLITUDE-THRESHOLD | absolute_voltage | source | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/119-absolute_voltage/receipt.json) |
| EEG-MUSCLE-DETECT | muscle_detect | source | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/120-muscle_detect/receipt.json) |
| EEG-BAD-CHANNEL-MARK | mark_channels | source | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/121-mark_channels/receipt.json) |
| EEG-BAD-CHANNEL-MARK | mark_repaired | source | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/122-mark_repaired/receipt.json) |
| EEG-BAD-SEGMENT-MARK | mark_segments | source | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/123-mark_segments/receipt.json) |
| EEG-BAD-CHANNEL-DROP | drop | source | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/124-drop/receipt.json) |
| EEG-ICA | ica_fit | method=fastica | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/125-ica_fit/receipt.json) |
| EEG-ICA | ica_fit | method=picard | 通过 | 通过 | 通过 | 通过 | 通过 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/126-ica_fit/receipt.json) |
| EEG-ICA | ica_fit | method=infomax | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/127-ica_fit/receipt.json) |
| EEG-ICA | ica_fit | method=picard,ortho=False,extended=False | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/128-ica_fit/receipt.json) |
| EEG-ICA | ica_fit | method=picard,ortho=False,extended=True | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/129-ica_fit/receipt.json) |
| EEG-ICA | ica_fit | method=picard,ortho=True,extended=False | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/130-ica_fit/receipt.json) |
| EEG-ICA | ica_fit | method=infomax,extended=False | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/131-ica_fit/receipt.json) |
| EEG-ICA | eog_assess | source | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/132-eog_assess/receipt.json) |
| EEG-ICA | ecg_assess | method=ctps | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/133-ecg_assess/receipt.json) |
| EEG-ICA | ecg_assess | method=correlation | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/134-ecg_assess/receipt.json) |
| EEG-ICA | ecg_assess | method=correlation,measure=correlation | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/135-ecg_assess/receipt.json) |
| EEG-ICA | muscle_assess | mode=spatial | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/136-muscle_assess/receipt.json) |
| EEG-ICA | muscle_assess | mode=slope | 通过 | 通过 | 通过 | 通过 | 通过 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/137-muscle_assess/receipt.json) |
| EEG-ICA | ica_apply | source | 通过 | 通过 | 通过 | 通过 | 通过 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/138-ica_apply/receipt.json) |
| EEG-EOG-REGRESSION | eog_fit | source | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/139-eog_fit/receipt.json) |
| EEG-EOG-REGRESSION | eog_apply | source | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/140-eog_apply/receipt.json) |
| EEG-SSP | ssp_apply | source | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/141-ssp_apply/receipt.json) |
| EEG-BRIDGE-DETECT | bridge_detect | source | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/142-bridge_detect/receipt.json) |
| EEG-BRIDGE-REPAIR | bridge_repair | source | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/143-bridge_repair/receipt.json) |
| EEG-INTERPOLATE | interpolate | source | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/144-interpolate/receipt.json) |
| EEG-INTERPOLATE | spherical | kernel=perrin | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/145-spherical/receipt.json) |
| EEG-INTERPOLATE | spherical | kernel=eeglab | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/146-spherical/receipt.json) |
| EEG-INTERPOLATE | interpolate_native | source | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/147-interpolate_native/receipt.json) |
| EEG-INTERPOLATE | interpolate_native | reset_bads=False,nonfinite=reject | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/148-interpolate_native/receipt.json) |
| EEG-INTERPOLATE | interpolate_native | reset_bads=False,nonfinite=propagate | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/149-interpolate_native/receipt.json) |
| EEG-INTERPOLATE | interpolate_native | reset_bads=True,nonfinite=reject | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/150-interpolate_native/receipt.json) |
| EEG-INTERPOLATE | trial_interpolate | source | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/151-trial_interpolate/receipt.json) |
| EEG-EPOCH | epoch | source | 通过 | 通过 | 通过 | 通过 | 通过 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/152-epoch/receipt.json) |
| EEG-EPOCH | epoch_with_nonfinite | source | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/153-epoch_with_nonfinite/receipt.json) |
| EEG-TRIAL-REJECT | reject_trials | source | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/154-reject_trials/receipt.json) |
| EEG-TRIAL-REJECT | drop_mask | source | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/155-drop_mask/receipt.json) |
| EEG-BASELINE | baseline | source | 通过 | 通过 | 通过 | 通过 | 通过 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/156-baseline/receipt.json) |
| EEG-ZAPLINE | zapline_plus | source | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/157-zapline_plus/receipt.json) |
| EEG-ZAPLINE | zapline_plus | noise_frequencies=[50.0],chunk_seconds=0,adaptive_sigma=False | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/158-zapline_plus/receipt.json) |
| EEG-ZAPLINE | zapline_plus | noise_frequencies=[50.0],chunk_seconds=0,adaptive_sigma=True | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/159-zapline_plus/receipt.json) |
| EEG-ZAPLINE | zapline_plus | noise_frequencies=[50.0],chunk_seconds=20,adaptive_sigma=True | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/160-zapline_plus/receipt.json) |
| EEG-ZAPLINE | zapline_plus | noise_frequencies=line,chunk_seconds=0,adaptive_sigma=False | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/161-zapline_plus/receipt.json) |
| EEG-ZAPLINE | zapline_plus | noise_frequencies=line,chunk_seconds=0,adaptive_sigma=True | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/162-zapline_plus/receipt.json) |
| EEG-ZAPLINE | zapline_plus | noise_frequencies=line,chunk_seconds=20,adaptive_sigma=False | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/163-zapline_plus/receipt.json) |
| EEG-ZAPLINE | zapline_plus | noise_frequencies=line,chunk_seconds=20,adaptive_sigma=True | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/164-zapline_plus/receipt.json) |
| EEG-ZAPLINE | zapline_plus | noise_frequencies=[],chunk_seconds=0,adaptive_sigma=False | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/165-zapline_plus/receipt.json) |
| EEG-ZAPLINE | zapline_plus | noise_frequencies=[],chunk_seconds=0,adaptive_sigma=True | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/166-zapline_plus/receipt.json) |
| EEG-ZAPLINE | zapline_plus | noise_frequencies=[],chunk_seconds=20,adaptive_sigma=False | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/167-zapline_plus/receipt.json) |
| EEG-ZAPLINE | zapline_plus | noise_frequencies=[],chunk_seconds=20,adaptive_sigma=True | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/168-zapline_plus/receipt.json) |
| EEG-BAD-CHANNEL-ENSEMBLE | prep_detect | source | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/169-prep_detect/receipt.json) |
| EEG-BAD-CHANNEL-ENSEMBLE | prep_detect | do_detrend=True,matlab_strict=False,reject_by_annotation=None | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/170-prep_detect/receipt.json) |
| EEG-BAD-CHANNEL-ENSEMBLE | prep_detect | do_detrend=True,matlab_strict=False,reject_by_annotation=omit | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/171-prep_detect/receipt.json) |
| EEG-BAD-CHANNEL-ENSEMBLE | prep_detect | do_detrend=False,matlab_strict=True,reject_by_annotation=None | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/172-prep_detect/receipt.json) |
| EEG-BAD-CHANNEL-ENSEMBLE | prep_detect | do_detrend=False,matlab_strict=False,reject_by_annotation=None | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/173-prep_detect/receipt.json) |
| EEG-BAD-CHANNEL-ENSEMBLE | prep_detect | do_detrend=False,matlab_strict=False,reject_by_annotation=omit | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/174-prep_detect/receipt.json) |
| EEG-BAD-CHANNEL-ENSEMBLE | prep_detect | criteria={'deviation': {}} | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/175-prep_detect/receipt.json) |
| EEG-BAD-CHANNEL-ENSEMBLE | prep_detect | criteria={'hfnoise': {}} | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/176-prep_detect/receipt.json) |
| EEG-BAD-CHANNEL-ENSEMBLE | prep_detect | criteria={'correlation': {}} | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/177-prep_detect/receipt.json) |
| EEG-BAD-CHANNEL-ENSEMBLE | prep_detect | criteria={'hfnoise': {}, 'correlation': {}, 'snr': {}} | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/178-prep_detect/receipt.json) |
| EEG-BAD-CHANNEL-ENSEMBLE | prep_detect | criteria={'deviation': {}, 'correlation': {}, 'ransac': {'channel_wise': True}} | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/179-prep_detect/receipt.json) |
| EEG-BAD-CHANNEL-ENSEMBLE | prep_detect | retained_bandwidth_policy=author_attenuated | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/180-prep_detect/receipt.json) |
| EEG-BAD-CHANNEL-ENSEMBLE | prep_detect_native | source | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/181-prep_detect_native/receipt.json) |
| EEG-BAD-CHANNEL-ENSEMBLE | prep_detect_native | do_detrend=True,ransac=True,correlation=True,channel_wise=True | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/182-prep_detect_native/receipt.json) |
| EEG-BAD-CHANNEL-ENSEMBLE | prep_detect_native | do_detrend=True,ransac=True,correlation=False,channel_wise=False | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/183-prep_detect_native/receipt.json) |
| EEG-BAD-CHANNEL-ENSEMBLE | prep_detect_native | do_detrend=True,ransac=True,correlation=False,channel_wise=True | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/184-prep_detect_native/receipt.json) |
| EEG-BAD-CHANNEL-ENSEMBLE | prep_detect_native | do_detrend=True,ransac=False,correlation=True,channel_wise=False | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/185-prep_detect_native/receipt.json) |
| EEG-BAD-CHANNEL-ENSEMBLE | prep_detect_native | do_detrend=True,ransac=False,correlation=False,channel_wise=False | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/186-prep_detect_native/receipt.json) |
| EEG-BAD-CHANNEL-ENSEMBLE | prep_detect_native | do_detrend=False,ransac=True,correlation=True,channel_wise=False | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/187-prep_detect_native/receipt.json) |
| EEG-BAD-CHANNEL-ENSEMBLE | prep_detect_native | do_detrend=False,ransac=True,correlation=True,channel_wise=True | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/188-prep_detect_native/receipt.json) |
| EEG-BAD-CHANNEL-ENSEMBLE | prep_detect_native | do_detrend=False,ransac=True,correlation=False,channel_wise=False | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/189-prep_detect_native/receipt.json) |
| EEG-BAD-CHANNEL-ENSEMBLE | prep_detect_native | do_detrend=False,ransac=True,correlation=False,channel_wise=True | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/190-prep_detect_native/receipt.json) |
| EEG-BAD-CHANNEL-ENSEMBLE | prep_detect_native | do_detrend=False,ransac=False,correlation=True,channel_wise=False | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/191-prep_detect_native/receipt.json) |
| EEG-BAD-CHANNEL-ENSEMBLE | prep_detect_native | do_detrend=False,ransac=False,correlation=False,channel_wise=False | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/192-prep_detect_native/receipt.json) |
| EEG-BAD-CHANNEL-ENSEMBLE | prep_detect_native | reject_by_annotation=omit | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/193-prep_detect_native/receipt.json) |
| EEG-BAD-CHANNEL-DEVIATION | deviation_detect | source | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/194-deviation_detect/receipt.json) |
| EEG-BAD-CHANNEL-DEVIATION | deviation_detect | do_detrend=True,matlab_strict=False,reject_by_annotation=None | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/195-deviation_detect/receipt.json) |
| EEG-BAD-CHANNEL-DEVIATION | deviation_detect | do_detrend=True,matlab_strict=False,reject_by_annotation=omit | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/196-deviation_detect/receipt.json) |
| EEG-BAD-CHANNEL-DEVIATION | deviation_detect | do_detrend=False,matlab_strict=True,reject_by_annotation=None | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/197-deviation_detect/receipt.json) |
| EEG-BAD-CHANNEL-DEVIATION | deviation_detect | do_detrend=False,matlab_strict=False,reject_by_annotation=None | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/198-deviation_detect/receipt.json) |
| EEG-BAD-CHANNEL-DEVIATION | deviation_detect | do_detrend=False,matlab_strict=False,reject_by_annotation=omit | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/199-deviation_detect/receipt.json) |
| EEG-BAD-CHANNEL-CORRELATION | correlation_detect | source | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/200-correlation_detect/receipt.json) |
| EEG-BAD-CHANNEL-CORRELATION | correlation_detect | do_detrend=True,matlab_strict=False,reject_by_annotation=None | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/201-correlation_detect/receipt.json) |
| EEG-BAD-CHANNEL-CORRELATION | correlation_detect | do_detrend=True,matlab_strict=False,reject_by_annotation=omit | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/202-correlation_detect/receipt.json) |
| EEG-BAD-CHANNEL-CORRELATION | correlation_detect | do_detrend=False,matlab_strict=True,reject_by_annotation=None | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/203-correlation_detect/receipt.json) |
| EEG-BAD-CHANNEL-CORRELATION | correlation_detect | do_detrend=False,matlab_strict=False,reject_by_annotation=None | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/204-correlation_detect/receipt.json) |
| EEG-BAD-CHANNEL-CORRELATION | correlation_detect | do_detrend=False,matlab_strict=False,reject_by_annotation=omit | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/205-correlation_detect/receipt.json) |
| EEG-BAD-CHANNEL-HF-RATIO | hf_ratio_detect | source | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/206-hf_ratio_detect/receipt.json) |
| EEG-BAD-CHANNEL-HF-RATIO | hf_ratio_detect | do_detrend=True,matlab_strict=False,reject_by_annotation=None | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/207-hf_ratio_detect/receipt.json) |
| EEG-BAD-CHANNEL-HF-RATIO | hf_ratio_detect | do_detrend=True,matlab_strict=False,reject_by_annotation=omit | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/208-hf_ratio_detect/receipt.json) |
| EEG-BAD-CHANNEL-HF-RATIO | hf_ratio_detect | do_detrend=False,matlab_strict=True,reject_by_annotation=None | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/209-hf_ratio_detect/receipt.json) |
| EEG-BAD-CHANNEL-HF-RATIO | hf_ratio_detect | do_detrend=False,matlab_strict=False,reject_by_annotation=None | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/210-hf_ratio_detect/receipt.json) |
| EEG-BAD-CHANNEL-HF-RATIO | hf_ratio_detect | do_detrend=False,matlab_strict=False,reject_by_annotation=omit | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/211-hf_ratio_detect/receipt.json) |
| EEG-BAD-CHANNEL-LINE-NOISE | line_noise_detect | source | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/212-line_noise_detect/receipt.json) |
| EEG-ICLABEL | iclabel_assess | backend=torch | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/213-iclabel_assess/receipt.json) |
| EEG-ICLABEL | iclabel_assess | backend=onnx | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/214-iclabel_assess/receipt.json) |
| EEG-MARA | mara_assess | source | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/215-mara_assess/receipt.json) |
| EEG-ADJUST | adjust_assess | source | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/216-adjust_assess/receipt.json) |
| EEG-FASTER-IC | faster_ic_assess | source | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/217-faster_ic_assess/receipt.json) |
| EEG-FASTER-IC | faster_ic_assess | metrics=['eog_correlation'] | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/218-faster_ic_assess/receipt.json) |
| EEG-FASTER-IC | faster_ic_assess | metrics=['kurtosis'] | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/219-faster_ic_assess/receipt.json) |
| EEG-FASTER-IC | faster_ic_assess | metrics=['power_gradient'] | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/220-faster_ic_assess/receipt.json) |
| EEG-FASTER-IC | faster_ic_assess | metrics=['hurst'] | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/221-faster_ic_assess/receipt.json) |
| EEG-FASTER-IC | faster_ic_assess | metrics=['median_gradient'] | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/222-faster_ic_assess/receipt.json) |
| EEG-FASTER-IC | faster_ic_assess | metrics=['line_noise'] | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/223-faster_ic_assess/receipt.json) |
| EEG-SASICA | sasica_assess | source | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/224-sasica_assess/receipt.json) |
| EEG-SASICA | sasica_assess | criteria={'autocorr': {}} | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/225-sasica_assess/receipt.json) |
| EEG-SASICA | sasica_assess | criteria={'focalcomp': {}} | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/226-sasica_assess/receipt.json) |
| EEG-SASICA | sasica_assess | criteria={'trialfoc': {}} | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/227-sasica_assess/receipt.json) |
| EEG-SASICA | sasica_assess | criteria={'snr': {}} | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/228-sasica_assess/receipt.json) |
| EEG-SASICA | sasica_assess | criteria={'eogcorr': {'vertical_channels': ['VEOG']}} | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/229-sasica_assess/receipt.json) |
| EEG-SASICA | sasica_assess | criteria={'chancorr': {'channels': ['C3', 'C4']}} | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/230-sasica_assess/receipt.json) |
| EEG-ASR | asr_fit | source | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/231-asr_fit/receipt.json) |
| EEG-ASR | asr_apply | source | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/232-asr_apply/receipt.json) |
| EEG-WICA | wica_apply | variant=ordinary | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/233-wica_apply/receipt.json) |
| EEG-WICA | wica_apply | variant=targeted | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/234-wica_apply/receipt.json) |
| EEG-WICA | wica_apply | variant=ordinary,clean_other=yes | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/235-wica_apply/receipt.json) |
| EEG-WICA | wica_apply | variant=targeted,clean_other=yes | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/236-wica_apply/receipt.json) |
| EEG-CCA | cca_fit | source | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/237-cca_fit/receipt.json) |
| EEG-CCA | cca_apply | source | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/238-cca_apply/receipt.json) |
| EEG-MWF | mwf_fit | rank=poseig | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/239-mwf_fit/receipt.json) |
| EEG-MWF | mwf_fit | rank=full | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/240-mwf_fit/receipt.json) |
| EEG-MWF | mwf_fit | rank=pct | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/241-mwf_fit/receipt.json) |
| EEG-MWF | mwf_fit | rank=first | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/242-mwf_fit/receipt.json) |
| EEG-MWF | mwf_fit | rank=poseig,delay=1,singlesided=False,treatnans=ignore | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/243-mwf_fit/receipt.json) |
| EEG-MWF | mwf_fit | rank=poseig,delay=1,singlesided=False,treatnans=artifact | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/244-mwf_fit/receipt.json) |
| EEG-MWF | mwf_fit | rank=poseig,delay=1,singlesided=False,treatnans=clean | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/245-mwf_fit/receipt.json) |
| EEG-MWF | mwf_fit | rank=poseig,delay=1,singlesided=True,treatnans=ignore | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/246-mwf_fit/receipt.json) |
| EEG-MWF | mwf_fit | rank=poseig,delay=1,singlesided=True,treatnans=artifact | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/247-mwf_fit/receipt.json) |
| EEG-MWF | mwf_fit | rank=poseig,delay=1,singlesided=True,treatnans=clean | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/248-mwf_fit/receipt.json) |
| EEG-MWF | mwf_fit | rank=full,delay=1,singlesided=False,treatnans=ignore | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/249-mwf_fit/receipt.json) |
| EEG-MWF | mwf_fit | rank=full,delay=1,singlesided=False,treatnans=artifact | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/250-mwf_fit/receipt.json) |
| EEG-MWF | mwf_fit | rank=full,delay=1,singlesided=False,treatnans=clean | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/251-mwf_fit/receipt.json) |
| EEG-MWF | mwf_fit | rank=full,delay=1,singlesided=True,treatnans=ignore | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/252-mwf_fit/receipt.json) |
| EEG-MWF | mwf_fit | rank=full,delay=1,singlesided=True,treatnans=artifact | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/253-mwf_fit/receipt.json) |
| EEG-MWF | mwf_fit | rank=full,delay=1,singlesided=True,treatnans=clean | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/254-mwf_fit/receipt.json) |
| EEG-MWF | mwf_fit | rank=pct,delay=1,singlesided=False,treatnans=ignore | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/255-mwf_fit/receipt.json) |
| EEG-MWF | mwf_fit | rank=pct,delay=1,singlesided=False,treatnans=artifact | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/256-mwf_fit/receipt.json) |
| EEG-MWF | mwf_fit | rank=pct,delay=1,singlesided=False,treatnans=clean | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/257-mwf_fit/receipt.json) |
| EEG-MWF | mwf_fit | rank=pct,delay=1,singlesided=True,treatnans=ignore | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/258-mwf_fit/receipt.json) |
| EEG-MWF | mwf_fit | rank=pct,delay=1,singlesided=True,treatnans=artifact | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/259-mwf_fit/receipt.json) |
| EEG-MWF | mwf_fit | rank=pct,delay=1,singlesided=True,treatnans=clean | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/260-mwf_fit/receipt.json) |
| EEG-MWF | mwf_fit | rank=first,delay=1,singlesided=False,treatnans=ignore | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/261-mwf_fit/receipt.json) |
| EEG-MWF | mwf_fit | rank=first,delay=1,singlesided=False,treatnans=artifact | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/262-mwf_fit/receipt.json) |
| EEG-MWF | mwf_fit | rank=first,delay=1,singlesided=False,treatnans=clean | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/263-mwf_fit/receipt.json) |
| EEG-MWF | mwf_fit | rank=first,delay=1,singlesided=True,treatnans=ignore | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/264-mwf_fit/receipt.json) |
| EEG-MWF | mwf_fit | rank=first,delay=1,singlesided=True,treatnans=artifact | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/265-mwf_fit/receipt.json) |
| EEG-MWF | mwf_fit | rank=first,delay=1,singlesided=True,treatnans=clean | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/266-mwf_fit/receipt.json) |
| EEG-MWF | mwf_apply | source | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/267-mwf_apply/receipt.json) |
| EEG-AUTOREJECT | autoreject_fit | mode=global | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/268-autoreject_fit/receipt.json) |
| EEG-AUTOREJECT | autoreject_fit | mode=local,thresh_method=bayesian_optimization | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/269-autoreject_fit/receipt.json) |
| EEG-AUTOREJECT | autoreject_fit | mode=local,thresh_method=random_search | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/270-autoreject_fit/receipt.json) |
| EEG-AUTOREJECT | autoreject_apply | source | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/271-autoreject_apply/receipt.json) |
| EEG-REGRESSION-BASELINE | regression_baseline_fit | source | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/272-regression_baseline_fit/receipt.json) |
| EEG-REGRESSION-BASELINE | regression_baseline_apply | source | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/273-regression_baseline_apply/receipt.json) |
| EEG-REGRESSION-BASELINE | regression_baseline_epochs_fit | source | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/274-regression_baseline_epochs_fit/receipt.json) |
| EEG-REGRESSION-BASELINE | regression_baseline_epochs_apply | source | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/275-regression_baseline_epochs_apply/receipt.json) |
| EEG-WINDOW-MAD | window_mad | source | 通过 | 通过 | 通过 | 通过 | 通过 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/276-window_mad/receipt.json) |
| EEG-WINDOW-MAD | blink_upper_bound | source | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/277-blink_upper_bound/receipt.json) |
| EEG-SPECTRAL-SLOPE | spectral_slope | mode=fieldtrip_mtmfft,retained_bandwidth_policy=require | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/278-spectral_slope/receipt.json) |
| EEG-SPECTRAL-SLOPE | spectral_slope | mode=fieldtrip_mtmfft,retained_bandwidth_policy=author_attenuated | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/279-spectral_slope/receipt.json) |
| EEG-SPECTRAL-SLOPE | spectral_slope | mode=relax_ic_welch,retained_bandwidth_policy=require | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/280-spectral_slope/receipt.json) |
| EEG-SPECTRAL-SLOPE | spectral_slope | mode=relax_ic_welch,retained_bandwidth_policy=author_attenuated | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/281-spectral_slope/receipt.json) |
| EEG-EOG-STEP | eog_step | statistic=trimmean95 | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/282-eog_step/receipt.json) |
| EEG-EOG-STEP | eog_step | statistic=mean | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/283-eog_step/receipt.json) |
| EEG-JOINT-PROBABILITY | joint_probability | source | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/284-joint_probability/receipt.json) |
| EEG-KURTOSIS | kurtosis | source | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/285-kurtosis/receipt.json) |
| EEG-BLINK-IQR | blink_iqr | variant=relax_2_0_1 | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/286-blink_iqr/receipt.json) |
| EEG-BLINK-IQR | blink_iqr | variant=repaired_indices | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/287-blink_iqr/receipt.json) |
| EEG-BLINK-IQR | blink_iqr | variant=relax_2_0_1,lowpass_Hz=6.0 | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/288-blink_iqr/receipt.json) |
| EEG-BLINK-IQR | blink_iqr | variant=repaired_indices,lowpass_Hz=6.0 | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/289-blink_iqr/receipt.json) |
| EEG-ROBUST-REFERENCE | prep_reference_fit | source | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/290-prep_reference_fit/receipt.json) |
| EEG-ROBUST-REFERENCE | prep_reference_fit | ransac=True,channel_wise=False,reject_by_annotation=omit | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/291-prep_reference_fit/receipt.json) |
| EEG-ROBUST-REFERENCE | prep_reference_fit | ransac=True,channel_wise=True,reject_by_annotation=None | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/292-prep_reference_fit/receipt.json) |
| EEG-ROBUST-REFERENCE | prep_reference_fit | ransac=True,channel_wise=True,reject_by_annotation=omit | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/293-prep_reference_fit/receipt.json) |
| EEG-ROBUST-REFERENCE | prep_reference_fit | ransac=False,channel_wise=False,reject_by_annotation=None | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/294-prep_reference_fit/receipt.json) |
| EEG-ROBUST-REFERENCE | prep_reference_fit | ransac=False,channel_wise=False,reject_by_annotation=omit | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/295-prep_reference_fit/receipt.json) |
| EEG-ROBUST-REFERENCE | prep_reference_finalize | source | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/296-prep_reference_finalize/receipt.json) |
| EEG-IC-BLINK-WEIGHTS | eye_weights | profile=relax_2_0_1 | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/297-eye_weights/receipt.json) |
| EEG-IC-BLINK-WEIGHTS | eye_weights | profile=repaired_units_indices | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/298-eye_weights/receipt.json) |
| EEG-CHANNEL-REJECTION-BUDGET | relax_budget | profile=relax_2_0_1 | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/299-relax_budget/receipt.json) |
| EEG-CHANNEL-REJECTION-BUDGET | relax_budget | profile=repaired_units_indices | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/300-relax_budget/receipt.json) |
| EEG-MUSCLE-TRIAL-DECISION | relax_muscle_trials | source | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/301-relax_muscle_trials/receipt.json) |
| EEG-AUTO-BAD-CHANNEL | detect_bad_channels | source | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/302-detect_bad_channels/receipt.json) |
| EEG-AUTO-BAD-CHANNEL | interpolate_bad_channels | source | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/303-interpolate_bad_channels/receipt.json) |
| EEG-ASR-AUTO | asr_clean | on_insufficient_calibration=error | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/304-asr_clean/receipt.json) |
| EEG-ASR-AUTO | asr_clean | on_insufficient_calibration=identity | 通过 | 通过 | 通过 | 通过 | 未通过/未执行 | [运行收据](E:/work/BrainAgent/.local/section-a-20260912/units-final-9/305-asr_clean/receipt.json) |

## 按单元汇总（全量 52 个）

| 单元 | op 数 | profile 数 | 数值通过 | 真实 EEG 覆盖 |
|---|---|---|---|---|
| EEG-CROP | 2 | 2 | 2 | 0 |
| EEG-DETREND | 1 | 2 | 2 | 0 |
| EEG-FILTER | 3 | 90 | 90 | 2 |
| EEG-SINE-REGRESSION | 2 | 4 | 4 | 0 |
| EEG-RESAMPLE | 5 | 5 | 5 | 0 |
| EEG-REREFERENCE | 4 | 10 | 10 | 3 |
| EEG-REST | 1 | 1 | 1 | 0 |
| EEG-CSD | 1 | 1 | 1 | 0 |
| EEG-BAD-CHANNEL-LOF | 1 | 1 | 1 | 0 |
| EEG-AMPLITUDE-THRESHOLD | 4 | 4 | 4 | 0 |
| EEG-MUSCLE-DETECT | 1 | 1 | 1 | 0 |
| EEG-BAD-CHANNEL-MARK | 2 | 2 | 2 | 0 |
| EEG-BAD-SEGMENT-MARK | 1 | 1 | 1 | 0 |
| EEG-BAD-CHANNEL-DROP | 1 | 1 | 1 | 0 |
| EEG-ICA | 5 | 14 | 14 | 3 |
| EEG-EOG-REGRESSION | 2 | 2 | 2 | 0 |
| EEG-SSP | 1 | 1 | 1 | 0 |
| EEG-BRIDGE-DETECT | 1 | 1 | 1 | 0 |
| EEG-BRIDGE-REPAIR | 1 | 1 | 1 | 0 |
| EEG-INTERPOLATE | 4 | 8 | 8 | 0 |
| EEG-EPOCH | 2 | 2 | 2 | 1 |
| EEG-TRIAL-REJECT | 2 | 2 | 2 | 0 |
| EEG-BASELINE | 1 | 1 | 1 | 1 |
| EEG-ZAPLINE | 1 | 12 | 12 | 0 |
| EEG-BAD-CHANNEL-ENSEMBLE | 2 | 25 | 25 | 0 |
| EEG-BAD-CHANNEL-DEVIATION | 1 | 6 | 6 | 0 |
| EEG-BAD-CHANNEL-CORRELATION | 1 | 6 | 6 | 0 |
| EEG-BAD-CHANNEL-HF-RATIO | 1 | 6 | 6 | 0 |
| EEG-BAD-CHANNEL-LINE-NOISE | 1 | 1 | 1 | 0 |
| EEG-ICLABEL | 1 | 2 | 2 | 0 |
| EEG-MARA | 1 | 1 | 1 | 0 |
| EEG-ADJUST | 1 | 1 | 1 | 0 |
| EEG-FASTER-IC | 1 | 7 | 7 | 0 |
| EEG-SASICA | 1 | 7 | 7 | 0 |
| EEG-ASR | 2 | 2 | 2 | 0 |
| EEG-WICA | 1 | 4 | 4 | 0 |
| EEG-CCA | 2 | 2 | 2 | 0 |
| EEG-MWF | 2 | 29 | 29 | 0 |
| EEG-AUTOREJECT | 2 | 4 | 4 | 0 |
| EEG-REGRESSION-BASELINE | 4 | 4 | 4 | 0 |
| EEG-WINDOW-MAD | 2 | 2 | 2 | 1 |
| EEG-SPECTRAL-SLOPE | 1 | 4 | 4 | 0 |
| EEG-EOG-STEP | 1 | 2 | 2 | 0 |
| EEG-JOINT-PROBABILITY | 1 | 1 | 1 | 0 |
| EEG-KURTOSIS | 1 | 1 | 1 | 0 |
| EEG-BLINK-IQR | 1 | 4 | 4 | 0 |
| EEG-ROBUST-REFERENCE | 2 | 7 | 7 | 0 |
| EEG-IC-BLINK-WEIGHTS | 1 | 2 | 2 | 0 |
| EEG-CHANNEL-REJECTION-BUDGET | 1 | 2 | 2 | 0 |
| EEG-MUSCLE-TRIAL-DECISION | 1 | 1 | 1 | 0 |
| EEG-AUTO-BAD-CHANNEL | 2 | 2 | 2 | 0 |
| EEG-ASR-AUTO | 1 | 2 | 2 | 0 |

## 每个操作的输入、输出与依赖

### EEG-CROP / crop

输入 `raw`；状态效应 `crop`；模型 `None`；拟合 `False`；显式决定 `False`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "tmin",
    "tmax",
    "events"
  ],
  "properties": {
    "tmin": {
      "type": "number"
    },
    "tmax": {
      "type": "number"
    },
    "events": {
      "type": "array",
      "runtime_binding": "$events"
    }
  }
}
```

输入合同：Raw 电位（V）；已确认任务范围和原始绝对样点 events。

输出合同：data=裁剪／拼接后的 Raw，events 按对应时基返回；crop_join 提供旧新样点映射。

### EEG-CROP / crop_join

输入 `raw`；状态效应 `crop_join`；模型 `None`；拟合 `False`；显式决定 `True`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "keep_intervals",
    "events",
    "decision_id"
  ],
  "properties": {
    "keep_intervals": {
      "type": "array"
    },
    "events": {
      "type": "array",
      "runtime_binding": "$events"
    },
    "decision_id": {
      "type": "string"
    }
  }
}
```

输入合同：Raw 电位（V）；已确认任务范围和原始绝对样点 events。

输出合同：data=裁剪／拼接后的 Raw，events 按对应时基返回；crop_join 提供旧新样点映射。

### EEG-DETREND / detrend

输入 `either`；状态效应 `preserve`；模型 `None`；拟合 `False`；显式决定 `False`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "type",
    "picks"
  ],
  "properties": {
    "type": {
      "type": "string",
      "enum": [
        "constant",
        "linear"
      ]
    },
    "picks": {
      "type": "array"
    }
  }
}
```

输入合同：Raw/Epochs 电位（V）；显式 EEG picks。Raw 的 edge、bad_acq_skip、boundary 处须先拆为连续段。

输出合同：data=同形、同采样率的 Raw/Epochs 电位；事件不变。

### EEG-FILTER / filter

输入 `raw`；状态效应 `preserve`；模型 `None`；拟合 `False`；显式决定 `False`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "l_freq",
    "h_freq",
    "method",
    "phase",
    "picks"
  ],
  "properties": {
    "l_freq": {
      "type": [
        "number",
        "null"
      ]
    },
    "h_freq": {
      "type": [
        "number",
        "null"
      ]
    },
    "method": {
      "type": "string",
      "enum": [
        "fir",
        "iir"
      ]
    },
    "phase": {
      "type": "string"
    },
    "picks": {
      "type": "array"
    },
    "fir_design": {
      "type": "string",
      "default": "firwin"
    },
    "fir_window": {
      "type": "string",
      "default": "hamming"
    },
    "filter_length": {
      "type": [
        "string",
        "integer"
      ],
      "default": "auto"
    },
    "l_trans_bandwidth": {
      "type": [
        "string",
        "number"
      ],
      "default": "auto"
    },
    "h_trans_bandwidth": {
      "type": [
        "string",
        "number"
      ],
      "default": "auto"
    },
    "pad": {
      "type": [
        "string",
        "integer"
      ],
      "default": "reflect_limited"
    },
    "annotation_policy": {
      "type": "string",
      "default": "raw",
      "enum": [
        "raw",
        "array"
      ]
    },
    "skip_by_annotation": {
      "type": "array",
      "default": [
        "edge",
        "bad_acq_skip",
        "boundary"
      ]
    },
    "nonfinite": {
      "type": "string",
      "default": "reject",
      "enum": [
        "reject",
        "propagate"
      ]
    }
  }
}
```

输入合同：filter：Raw 电位 V，显式 EEG picks；raw 策略按注释前缀分段，array 策略处理整个所选数组。butter：Raw 或已加载 Epochs，显式 eeg/eog/ecg/emg/misc 电位通道；Raw 已按采集断点拆分。 notch：有限 Raw、显式 EEG picks，已按采集断点拆分。

输出合同：同类型 Raw/Epochs 电位（V）；未选通道保持，时间轴及 Trial 身份保持。

### EEG-FILTER / butter

输入 `either`；状态效应 `preserve`；模型 `None`；拟合 `False`；显式决定 `False`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "kind",
    "l_freq",
    "h_freq",
    "prototype_order",
    "phase",
    "picks",
    "padlen"
  ],
  "properties": {
    "kind": {
      "type": "string",
      "enum": [
        "highpass",
        "lowpass",
        "bandpass",
        "bandstop"
      ]
    },
    "l_freq": {
      "type": [
        "number",
        "null"
      ]
    },
    "h_freq": {
      "type": [
        "number",
        "null"
      ]
    },
    "prototype_order": {
      "type": "integer",
      "exclusiveMinimum": 0,
      "maximum": 12
    },
    "phase": {
      "type": "string"
    },
    "picks": {
      "type": "array"
    },
    "padlen": {
      "type": [
        "integer",
        "null"
      ]
    }
  }
}
```

输入合同：filter：Raw 电位 V，显式 EEG picks；raw 策略按注释前缀分段，array 策略处理整个所选数组。butter：Raw 或已加载 Epochs，显式 eeg/eog/ecg/emg/misc 电位通道；Raw 已按采集断点拆分。 notch：有限 Raw、显式 EEG picks，已按采集断点拆分。

输出合同：同类型 Raw/Epochs 电位（V）；未选通道保持，时间轴及 Trial 身份保持。

### EEG-FILTER / notch

输入 `raw`；状态效应 `preserve`；模型 `None`；拟合 `False`；显式决定 `False`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "freqs",
    "picks"
  ],
  "properties": {
    "freqs": {
      "type": "array"
    },
    "picks": {
      "type": "array"
    }
  }
}
```

输入合同：filter：Raw 电位 V，显式 EEG picks；raw 策略按注释前缀分段，array 策略处理整个所选数组。butter：Raw 或已加载 Epochs，显式 eeg/eog/ecg/emg/misc 电位通道；Raw 已按采集断点拆分。 notch：有限 Raw、显式 EEG picks，已按采集断点拆分。

输出合同：同类型 Raw/Epochs 电位（V）；未选通道保持，时间轴及 Trial 身份保持。

### EEG-SINE-REGRESSION / spectrum_fit

输入 `raw`；状态效应 `preserve`；模型 `None`；拟合 `False`；显式决定 `False`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "freqs",
    "picks"
  ],
  "properties": {
    "freqs": {
      "type": "array"
    },
    "picks": {
      "type": "array"
    },
    "mt_bandwidth": {
      "type": "number",
      "default": 2.0
    },
    "p_value": {
      "type": "number",
      "default": 0.01,
      "minimum": 0,
      "maximum": 1
    },
    "filter_length": {
      "type": [
        "string",
        "integer"
      ],
      "default": "10s"
    },
    "annotation_policy": {
      "type": "string",
      "default": "array",
      "enum": [
        "raw",
        "array"
      ]
    },
    "nonfinite": {
      "type": "string",
      "default": "reject",
      "enum": [
        "reject",
        "propagate"
      ]
    }
  }
}
```

输入合同：Raw 电位（V）。spectrum_fit：显式 EEG picks，对整个数组处理，注释不分段。cleanline：有限且未标坏的 EEG picks；已按采集断点拆为连续段，窗口不跨断点。

输出合同：同形 Raw 电位（V），所选正弦估计被扣除；未选通道、时间轴、事件和频带元数据保持。cleanline 保留末个完整窗后的尾段。

### EEG-SINE-REGRESSION / cleanline

输入 `raw`；状态效应 `preserve`；模型 `None`；拟合 `False`；显式决定 `False`。

依赖：`{}`；资产：`['source_root', 'octave_path']`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "source_root",
    "octave_path",
    "picks",
    "line_frequencies",
    "bandwidth",
    "scan_bandwidth",
    "window_seconds",
    "step_seconds",
    "alpha",
    "pad",
    "smoothing",
    "max_iterations",
    "timeout_seconds",
    "tail_policy"
  ],
  "properties": {
    "source_root": {
      "type": "string"
    },
    "octave_path": {
      "type": "string"
    },
    "picks": {
      "type": "array"
    },
    "line_frequencies": {
      "type": "array"
    },
    "bandwidth": {
      "type": "number",
      "exclusiveMinimum": 0
    },
    "scan_bandwidth": {
      "type": [
        "number",
        "null"
      ]
    },
    "window_seconds": {
      "type": "number"
    },
    "step_seconds": {
      "type": "number"
    },
    "alpha": {
      "type": "number",
      "minimum": 0,
      "maximum": 1
    },
    "pad": {
      "type": [
        "string",
        "integer"
      ]
    },
    "smoothing": {
      "type": "integer"
    },
    "max_iterations": {
      "type": "integer"
    },
    "timeout_seconds": {
      "type": "number",
      "exclusiveMinimum": 0
    },
    "tail_policy": {
      "type": "string",
      "enum": [
        "preserve"
      ]
    }
  }
}
```

输入合同：Raw 电位（V）。spectrum_fit：显式 EEG picks，对整个数组处理，注释不分段。cleanline：有限且未标坏的 EEG picks；已按采集断点拆为连续段，窗口不跨断点。

输出合同：同形 Raw 电位（V），所选正弦估计被扣除；未选通道、时间轴、事件和频带元数据保持。cleanline 保留末个完整窗后的尾段。

### EEG-RESAMPLE / resample

输入 `either`；状态效应 `resample`；模型 `None`；拟合 `False`；显式决定 `False`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "sfreq",
    "events"
  ],
  "properties": {
    "sfreq": {
      "type": "number",
      "exclusiveMinimum": 0
    },
    "events": {
      "type": "array",
      "runtime_binding": "$events"
    }
  }
}
```

输入合同：resample 接受 Raw/Epochs；FFT及显式FIR变体接受连续 Raw。电位V，events为当前输入绝对样点。 decimate仅接受已加载有限Epochs；decim>1时输入lowpass≤目标sfreq/3。

输出合同：data=同类电位对象，sfreq/样点数改变；Epochs.events 继续表示原记录样点。 decimate按时间零点和offset抽取，原始events/selection/Trial身份保留。

### EEG-RESAMPLE / resample_fft

输入 `raw`；状态效应 `resample`；模型 `None`；拟合 `False`；显式决定 `False`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "sfreq",
    "events",
    "npad",
    "window",
    "pad"
  ],
  "properties": {
    "sfreq": {
      "type": "number",
      "exclusiveMinimum": 0
    },
    "events": {
      "type": "array",
      "runtime_binding": "$events"
    },
    "npad": {
      "type": [
        "integer",
        "string"
      ]
    },
    "window": {
      "type": [
        "string",
        "array",
        "null"
      ]
    },
    "pad": {
      "type": [
        "string",
        "integer"
      ]
    }
  }
}
```

输入合同：resample 接受 Raw/Epochs；FFT及显式FIR变体接受连续 Raw。电位V，events为当前输入绝对样点。 decimate仅接受已加载有限Epochs；decim>1时输入lowpass≤目标sfreq/3。

输出合同：data=同类电位对象，sfreq/样点数改变；Epochs.events 继续表示原记录样点。 decimate按时间零点和offset抽取，原始events/selection/Trial身份保留。

### EEG-RESAMPLE / resample_fir

输入 `raw`；状态效应 `resample`；模型 `None`；拟合 `False`；显式决定 `False`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "sfreq",
    "events",
    "kernel"
  ],
  "properties": {
    "sfreq": {
      "type": "number",
      "exclusiveMinimum": 0
    },
    "events": {
      "type": "array",
      "runtime_binding": "$events"
    },
    "kernel": {
      "type": [
        "string",
        "array"
      ]
    }
  }
}
```

输入合同：resample 接受 Raw/Epochs；FFT及显式FIR变体接受连续 Raw。电位V，events为当前输入绝对样点。 decimate仅接受已加载有限Epochs；decim>1时输入lowpass≤目标sfreq/3。

输出合同：data=同类电位对象，sfreq/样点数改变；Epochs.events 继续表示原记录样点。 decimate按时间零点和offset抽取，原始events/selection/Trial身份保留。

### EEG-RESAMPLE / resample_eeglab

输入 `raw`；状态效应 `resample`；模型 `None`；拟合 `False`；显式决定 `False`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "sfreq",
    "events",
    "cutoff",
    "transition",
    "ripple",
    "beta"
  ],
  "properties": {
    "sfreq": {
      "type": "number",
      "exclusiveMinimum": 0
    },
    "events": {
      "type": "array",
      "runtime_binding": "$events"
    },
    "cutoff": {
      "type": "number"
    },
    "transition": {
      "type": "number"
    },
    "ripple": {
      "type": "number"
    },
    "beta": {
      "type": "number"
    }
  }
}
```

输入合同：resample 接受 Raw/Epochs；FFT及显式FIR变体接受连续 Raw。电位V，events为当前输入绝对样点。 decimate仅接受已加载有限Epochs；decim>1时输入lowpass≤目标sfreq/3。

输出合同：data=同类电位对象，sfreq/样点数改变；Epochs.events 继续表示原记录样点。 decimate按时间零点和offset抽取，原始events/selection/Trial身份保留。

### EEG-RESAMPLE / decimate

输入 `epochs`；状态效应 `decimate`；模型 `None`；拟合 `False`；显式决定 `False`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "decim",
    "offset"
  ],
  "properties": {
    "decim": {
      "type": "integer",
      "exclusiveMinimum": 0
    },
    "offset": {
      "type": "integer"
    }
  }
}
```

输入合同：resample 接受 Raw/Epochs；FFT及显式FIR变体接受连续 Raw。电位V，events为当前输入绝对样点。 decimate仅接受已加载有限Epochs；decim>1时输入lowpass≤目标sfreq/3。

输出合同：data=同类电位对象，sfreq/样点数改变；Epochs.events 继续表示原记录样点。 decimate按时间零点和offset抽取，原始events/selection/Trial身份保留。

### EEG-REREFERENCE / reference

输入 `either`；状态效应 `reference`；模型 `None`；拟合 `False`；显式决定 `False`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "ref_channels"
  ],
  "properties": {
    "ref_channels": {
      "type": [
        "string",
        "array"
      ]
    }
  }
}
```

输入合同：Raw 或已加载 Epochs，电位 V；供体和应用目标均为显式唯一 EEG 名称，可包含已有坏道标记；NaN 仅显式 propagate。

输出合同：estimate 返回原数据副本和参考向量模型；apply 仅从 targets 扣除模型向量，标记已应用参考。

### EEG-REREFERENCE / relax_car

输入 `raw`；状态效应 `reference_channels`；模型 `None`；拟合 `False`；显式决定 `True`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "original_channels",
    "confirmed_bad_channels",
    "reference_id"
  ],
  "properties": {
    "original_channels": {
      "type": "array"
    },
    "confirmed_bad_channels": {
      "type": "array"
    },
    "reference_id": {
      "type": "string",
      "runtime_binding": "$reference_id"
    }
  }
}
```

输入合同：Raw 或已加载 Epochs，电位 V；供体和应用目标均为显式唯一 EEG 名称，可包含已有坏道标记；NaN 仅显式 propagate。

输出合同：estimate 返回原数据副本和参考向量模型；apply 仅从 targets 扣除模型向量，标记已应用参考。

### EEG-REREFERENCE / reference_estimate

输入 `either`；状态效应 `model`；模型 `reference`；拟合 `False`；显式决定 `False`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "donors",
    "reference_id"
  ],
  "properties": {
    "donors": {
      "type": "array"
    },
    "reference_id": {
      "type": "string",
      "runtime_binding": "$reference_id"
    },
    "estimator": {
      "type": "string",
      "default": "nanmean",
      "enum": [
        "nanmean",
        "nanmedian"
      ]
    },
    "nonfinite": {
      "type": "string",
      "default": "reject",
      "enum": [
        "reject",
        "propagate"
      ]
    }
  }
}
```

输入合同：Raw 或已加载 Epochs，电位 V；供体和应用目标均为显式唯一 EEG 名称，可包含已有坏道标记；NaN 仅显式 propagate。

输出合同：estimate 返回原数据副本和参考向量模型；apply 仅从 targets 扣除模型向量，标记已应用参考。

### EEG-REREFERENCE / reference_apply

输入 `either`；状态效应 `reference`；模型 `reference`；拟合 `False`；显式决定 `False`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "targets"
  ],
  "properties": {
    "targets": {
      "type": "array"
    },
    "nonfinite": {
      "type": "string",
      "default": "reject",
      "enum": [
        "reject",
        "propagate"
      ]
    }
  }
}
```

输入合同：Raw 或已加载 Epochs，电位 V；供体和应用目标均为显式唯一 EEG 名称，可包含已有坏道标记；NaN 仅显式 propagate。

输出合同：estimate 返回原数据副本和参考向量模型；apply 仅从 targets 扣除模型向量，标记已应用参考。

### EEG-REST / rest

输入 `either`；状态效应 `reference`；模型 `None`；拟合 `False`；显式决定 `False`。

依赖：`{}`；资产：`['forward']`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "forward"
  ],
  "properties": {
    "forward": {
      "type": "object"
    }
  }
}
```

输入合同：Raw/Epochs 电位（V）；mne.Forward 与通道、几何和参考兼容。

输出合同：data=同形 REST 参考电位（V）。

### EEG-CSD / csd

输入 `either`；状态效应 `csd`；模型 `None`；拟合 `False`；显式决定 `False`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "sphere",
    "lambda2",
    "stiffness",
    "n_legendre_terms"
  ],
  "properties": {
    "sphere": {
      "type": [
        "array",
        "string",
        "null"
      ]
    },
    "lambda2": {
      "type": "number"
    },
    "stiffness": {
      "type": "number"
    },
    "n_legendre_terms": {
      "type": "integer",
      "exclusiveMinimum": 0
    }
  }
}
```

输入合同：头皮 Raw/Epochs 电位（V）；坐标和球模型有效，info.bads 中无坏 EEG。

输出合同：data=同形空间导数（V/m²），通道类型 csd；后续保留 spatial_derivative 角色。

### EEG-BAD-CHANNEL-LOF / lof_detect

输入 `raw`；状态效应 `preserve`；模型 `None`；拟合 `False`；显式决定 `False`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "n_neighbors",
    "threshold",
    "metric"
  ],
  "properties": {
    "n_neighbors": {
      "type": "integer",
      "exclusiveMinimum": 0
    },
    "threshold": {
      "type": [
        "number",
        "string"
      ]
    },
    "metric": {
      "type": "string"
    }
  }
}
```

输入合同：连续 Raw 电位（V），至少2个好 EEG；候选与分数使用同一好道轴。

输出合同：data=原波形副本；现有 bads 不变。

### EEG-AMPLITUDE-THRESHOLD / amplitude_detect

输入 `raw`；状态效应 `preserve`；模型 `None`；拟合 `False`；显式决定 `False`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "peak",
    "flat",
    "bad_percent",
    "min_duration",
    "picks"
  ],
  "properties": {
    "peak": {
      "type": [
        "number",
        "object",
        "null"
      ]
    },
    "flat": {
      "type": [
        "number",
        "object",
        "null"
      ]
    },
    "bad_percent": {
      "type": "number",
      "minimum": 0,
      "maximum": 100
    },
    "min_duration": {
      "type": "number"
    },
    "picks": {
      "type": "array"
    }
  }
}
```

输入合同：电位单位 V。amplitude_detect：全部输入有限的连续 Raw，显式 EEG picks；flat_detect/amplitude_windows：Raw，排除已标坏 EEG，默认避开 BAD/EDGE 注释，valid_intervals 为原样点半开区间。absolute_voltage：Raw 或已加载 Epochs，默认未标坏 EEG，显式 picks 可含辅助通道；后三项要求选中数据有限。

输出合同：data 为原信号副本；数据、通道、既有 bads、注释和事件保持。候选掩码或坏道名称位于 artifacts。

### EEG-AMPLITUDE-THRESHOLD / flat_detect

输入 `raw`；状态效应 `preserve`；模型 `None`；拟合 `False`；显式决定 `False`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [],
  "properties": {
    "max_flatline_duration": {
      "type": "number",
      "default": 5.0,
      "exclusiveMinimum": 0
    },
    "tolerance_V": {
      "type": "number",
      "default": 1e-15
    },
    "valid_intervals": {
      "type": [
        "array",
        "null"
      ],
      "default": null
    }
  }
}
```

输入合同：电位单位 V。amplitude_detect：全部输入有限的连续 Raw，显式 EEG picks；flat_detect/amplitude_windows：Raw，排除已标坏 EEG，默认避开 BAD/EDGE 注释，valid_intervals 为原样点半开区间。absolute_voltage：Raw 或已加载 Epochs，默认未标坏 EEG，显式 picks 可含辅助通道；后三项要求选中数据有限。

输出合同：data 为原信号副本；数据、通道、既有 bads、注释和事件保持。候选掩码或坏道名称位于 artifacts。

### EEG-AMPLITUDE-THRESHOLD / amplitude_windows

输入 `raw`；状态效应 `preserve`；模型 `None`；拟合 `False`；显式决定 `False`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [],
  "properties": {
    "window_s": {
      "type": "number",
      "default": 1.0,
      "exclusiveMinimum": 0
    },
    "stride_s": {
      "type": "number",
      "default": 0.5,
      "exclusiveMinimum": 0
    },
    "tail": {
      "type": "string",
      "default": "drop",
      "enum": [
        "drop"
      ]
    },
    "valid_intervals": {
      "type": [
        "array",
        "null"
      ],
      "default": null
    },
    "min_windows": {
      "type": "integer",
      "default": 1,
      "exclusiveMinimum": 0
    },
    "peak_to_peak_limit_V": {
      "type": "number",
      "default": 0.0001
    },
    "frac_bad": {
      "type": "number",
      "default": 0.25,
      "minimum": 0,
      "maximum": 1
    }
  }
}
```

输入合同：电位单位 V。amplitude_detect：全部输入有限的连续 Raw，显式 EEG picks；flat_detect/amplitude_windows：Raw，排除已标坏 EEG，默认避开 BAD/EDGE 注释，valid_intervals 为原样点半开区间。absolute_voltage：Raw 或已加载 Epochs，默认未标坏 EEG，显式 picks 可含辅助通道；后三项要求选中数据有限。

输出合同：data 为原信号副本；数据、通道、既有 bads、注释和事件保持。候选掩码或坏道名称位于 artifacts。

### EEG-AMPLITUDE-THRESHOLD / absolute_voltage

输入 `raw`；状态效应 `preserve`；模型 `None`；拟合 `False`；显式决定 `False`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [],
  "properties": {
    "limit_V": {
      "type": "number",
      "default": 0.001
    },
    "picks": {
      "type": [
        "array",
        "null"
      ],
      "default": null
    }
  }
}
```

输入合同：电位单位 V。amplitude_detect：全部输入有限的连续 Raw，显式 EEG picks；flat_detect/amplitude_windows：Raw，排除已标坏 EEG，默认避开 BAD/EDGE 注释，valid_intervals 为原样点半开区间。absolute_voltage：Raw 或已加载 Epochs，默认未标坏 EEG，显式 picks 可含辅助通道；后三项要求选中数据有限。

输出合同：data 为原信号副本；数据、通道、既有 bads、注释和事件保持。候选掩码或坏道名称位于 artifacts。

### EEG-MUSCLE-DETECT / muscle_detect

输入 `raw`；状态效应 `preserve`；模型 `None`；拟合 `False`；显式决定 `False`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "threshold",
    "filter_freq",
    "min_length_good"
  ],
  "properties": {
    "threshold": {
      "type": [
        "number",
        "string"
      ]
    },
    "filter_freq": {
      "type": "array"
    },
    "min_length_good": {
      "type": "number"
    }
  }
}
```

输入合同：连续 Raw EEG 电位（V）；采样率和真实采集带宽覆盖 filter_freq。

输出合同：data=原波形副本，现有标记不变。

### EEG-BAD-CHANNEL-MARK / mark_channels

输入 `either`；状态效应 `mark`；模型 `None`；拟合 `False`；显式决定 `True`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "bads",
    "max_fraction"
  ],
  "properties": {
    "bads": {
      "type": "array"
    },
    "max_fraction": {
      "type": "number",
      "minimum": 0,
      "maximum": 1
    }
  }
}
```

输入合同：Raw/Epochs电位（V）；标记依据当前输入坏道决定，清除依据当前输入已完成的修复决定。

输出合同：data=波形不变、bads更新的同类型对象；mark_channels求并集，mark_repaired清除确认修复项。

### EEG-BAD-CHANNEL-MARK / mark_repaired

输入 `either`；状态效应 `mark`；模型 `None`；拟合 `False`；显式决定 `True`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "repaired_channels",
    "decision_id"
  ],
  "properties": {
    "repaired_channels": {
      "type": "array"
    },
    "decision_id": {
      "type": "string"
    }
  }
}
```

输入合同：Raw/Epochs电位（V）；标记依据当前输入坏道决定，清除依据当前输入已完成的修复决定。

输出合同：data=波形不变、bads更新的同类型对象；mark_channels求并集，mark_repaired清除确认修复项。

### EEG-BAD-SEGMENT-MARK / mark_segments

输入 `raw`；状态效应 `annotations`；模型 `None`；拟合 `False`；显式决定 `True`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "annotations",
    "frame"
  ],
  "properties": {
    "annotations": {
      "type": "object"
    },
    "frame": {
      "type": "object"
    }
  }
}
```

输入合同：Raw 电位（V）；当前输入版本的 BAD 决定；Annotations.orig_time 与 Raw 一致。

输出合同：data=原波形副本；保留原注释并追加 BAD 注释。

### EEG-BAD-CHANNEL-DROP / drop

输入 `either`；状态效应 `channels`；模型 `None`；拟合 `False`；显式决定 `True`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "channels",
    "reason"
  ],
  "properties": {
    "channels": {
      "type": "array"
    },
    "reason": {
      "type": "string"
    }
  }
}
```

输入合同：Raw/Epochs 电位（V）；指定 EEG 已在 info.bads 中，至少保留一个好 EEG；决定来源对应当前输入。

输出合同：data=剔除指定坏道后的对象；采样率、时间和事件保持。

### EEG-ICA / ica_fit

输入 `either`；状态效应 `model`；模型 `ica`；拟合 `True`；显式决定 `False`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "method",
    "n_components",
    "seed",
    "max_iter",
    "scope",
    "reference_id"
  ],
  "properties": {
    "method": {
      "type": "string",
      "enum": [
        "fastica",
        "picard",
        "infomax"
      ]
    },
    "n_components": {
      "type": [
        "integer",
        "number",
        "null"
      ]
    },
    "seed": {
      "type": "integer"
    },
    "max_iter": {
      "type": [
        "integer",
        "string"
      ]
    },
    "scope": {
      "type": "object",
      "runtime_binding": "$scope"
    },
    "reference_id": {
      "type": "string",
      "runtime_binding": "$reference_id"
    },
    "tol": {
      "type": [
        "number",
        "null"
      ],
      "default": null
    },
    "ortho": {
      "type": [
        "boolean",
        "null"
      ],
      "default": null
    },
    "extended": {
      "type": [
        "boolean",
        "null"
      ],
      "default": null
    },
    "reject": {
      "type": [
        "object",
        "null"
      ],
      "default": null
    },
    "flat": {
      "type": [
        "number",
        "object",
        "null"
      ],
      "default": null
    },
    "tstep": {
      "type": "number",
      "default": 2.0,
      "exclusiveMinimum": 0
    }
  }
}
```

输入合同：已加载 Raw/Epochs 电位 V；通道、参考和校准范围已确认。拟合副本高通：FastICA/Infomax ≥1 Hz，Picard ≥0.5 Hz；Epochs baseline=None。

输出合同：fit 返回 ICA 模型与同数据副本；assess 返回候选成分和分数；apply 返回剔除指定 IC 后的数据。

### EEG-ICA / eog_assess

输入 `either`；状态效应 `preserve`；模型 `ica`；拟合 `False`；显式决定 `False`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "ch_name",
    "threshold",
    "l_freq",
    "h_freq",
    "reference_id"
  ],
  "properties": {
    "ch_name": {
      "type": "string"
    },
    "threshold": {
      "type": [
        "number",
        "string"
      ]
    },
    "l_freq": {
      "type": [
        "number",
        "null"
      ]
    },
    "h_freq": {
      "type": [
        "number",
        "null"
      ]
    },
    "reference_id": {
      "type": "string",
      "runtime_binding": "$reference_id"
    },
    "reference_role": {
      "type": [
        "string",
        "null"
      ],
      "default": null
    },
    "channel_decision_id": {
      "type": [
        "string",
        "null"
      ],
      "default": null
    }
  }
}
```

输入合同：已加载 Raw/Epochs 电位 V；通道、参考和校准范围已确认。拟合副本高通：FastICA/Infomax ≥1 Hz，Picard ≥0.5 Hz；Epochs baseline=None。

输出合同：fit 返回 ICA 模型与同数据副本；assess 返回候选成分和分数；apply 返回剔除指定 IC 后的数据。

### EEG-ICA / ecg_assess

输入 `raw`；状态效应 `preserve`；模型 `ica`；拟合 `False`；显式决定 `False`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "ch_name",
    "method",
    "threshold",
    "reference_id"
  ],
  "properties": {
    "ch_name": {
      "type": "string"
    },
    "method": {
      "type": "string",
      "enum": [
        "ctps",
        "correlation"
      ]
    },
    "threshold": {
      "type": [
        "number",
        "string"
      ]
    },
    "reference_id": {
      "type": "string",
      "runtime_binding": "$reference_id"
    },
    "l_freq": {
      "type": [
        "number",
        "null"
      ],
      "default": 8.0
    },
    "h_freq": {
      "type": [
        "number",
        "null"
      ],
      "default": 16.0
    },
    "measure": {
      "type": "string",
      "default": "zscore"
    },
    "reference_role": {
      "type": [
        "string",
        "null"
      ],
      "default": null
    },
    "channel_decision_id": {
      "type": [
        "string",
        "null"
      ],
      "default": null
    }
  }
}
```

输入合同：已加载 Raw/Epochs 电位 V；通道、参考和校准范围已确认。拟合副本高通：FastICA/Infomax ≥1 Hz，Picard ≥0.5 Hz；Epochs baseline=None。

输出合同：fit 返回 ICA 模型与同数据副本；assess 返回候选成分和分数；apply 返回剔除指定 IC 后的数据。

### EEG-ICA / muscle_assess

输入 `either`；状态效应 `preserve`；模型 `ica`；拟合 `False`；显式决定 `False`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "mode",
    "reference_id"
  ],
  "properties": {
    "mode": {
      "type": "string",
      "enum": [
        "spatial",
        "slope"
      ]
    },
    "reference_id": {
      "type": "string",
      "runtime_binding": "$reference_id"
    },
    "threshold": {
      "type": [
        "number",
        "string"
      ],
      "default": 0.5
    },
    "l_freq": {
      "type": [
        "number",
        "null"
      ],
      "default": 7.0
    },
    "h_freq": {
      "type": [
        "number",
        "null"
      ],
      "default": 45.0
    },
    "sphere": {
      "type": [
        "array",
        "string",
        "null"
      ],
      "default": null
    }
  }
}
```

输入合同：已加载 Raw/Epochs 电位 V；通道、参考和校准范围已确认。拟合副本高通：FastICA/Infomax ≥1 Hz，Picard ≥0.5 Hz；Epochs baseline=None。

输出合同：fit 返回 ICA 模型与同数据副本；assess 返回候选成分和分数；apply 返回剔除指定 IC 后的数据。

### EEG-ICA / ica_apply

输入 `either`；状态效应 `preserve`；模型 `ica`；拟合 `False`；显式决定 `True`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "exclude",
    "reference_id"
  ],
  "properties": {
    "exclude": {
      "type": "array"
    },
    "reference_id": {
      "type": "string",
      "runtime_binding": "$reference_id"
    }
  }
}
```

输入合同：已加载 Raw/Epochs 电位 V；通道、参考和校准范围已确认。拟合副本高通：FastICA/Infomax ≥1 Hz，Picard ≥0.5 Hz；Epochs baseline=None。

输出合同：fit 返回 ICA 模型与同数据副本；assess 返回候选成分和分数；apply 返回剔除指定 IC 后的数据。

### EEG-EOG-REGRESSION / eog_fit

输入 `raw`；状态效应 `model`；模型 `eog`；拟合 `True`；显式决定 `False`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "picks",
    "picks_artifact",
    "scope",
    "reference_id"
  ],
  "properties": {
    "picks": {
      "type": "array"
    },
    "picks_artifact": {
      "type": "array"
    },
    "scope": {
      "type": "object",
      "runtime_binding": "$scope"
    },
    "reference_id": {
      "type": "string",
      "runtime_binding": "$reference_id"
    }
  }
}
```

输入合同：Raw/Epochs 电位（V）；EEG/EOG 明确、参考固定，未做基线；拟合不跨断点/BAD 段，所选拟合通道无坏道。

输出合同：eog_fit：原波形副本及回归 model；eog_apply：校正波形及原 model。

### EEG-EOG-REGRESSION / eog_apply

输入 `either`；状态效应 `preserve`；模型 `eog`；拟合 `False`；显式决定 `False`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "reference_id"
  ],
  "properties": {
    "reference_id": {
      "type": "string",
      "runtime_binding": "$reference_id"
    }
  }
}
```

输入合同：Raw/Epochs 电位（V）；EEG/EOG 明确、参考固定，未做基线；拟合不跨断点/BAD 段，所选拟合通道无坏道。

输出合同：eog_fit：原波形副本及回归 model；eog_apply：校正波形及原 model。

### EEG-SSP / ssp_apply

输入 `either`；状态效应 `reference`；模型 `None`；拟合 `False`；显式决定 `True`。

依赖：`{}`；资产：`['projs']`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "projs"
  ],
  "properties": {
    "projs": {
      "type": [
        "array",
        "object"
      ]
    }
  }
}
```

输入合同：Raw/Epochs 电位（V）；非空、已审核 MNE Projection 列表；无已有 projector，未做基线。

输出合同：data=投影后的电位波形。

### EEG-BRIDGE-DETECT / bridge_detect

输入 `raw`；状态效应 `preserve`；模型 `None`；拟合 `False`；显式决定 `False`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "lm_cutoff",
    "epoch_threshold",
    "l_freq",
    "h_freq",
    "epoch_duration"
  ],
  "properties": {
    "lm_cutoff": {
      "type": "number"
    },
    "epoch_threshold": {
      "type": "number"
    },
    "l_freq": {
      "type": [
        "number",
        "null"
      ]
    },
    "h_freq": {
      "type": [
        "number",
        "null"
      ]
    },
    "epoch_duration": {
      "type": "number",
      "exclusiveMinimum": 0
    }
  }
}
```

输入合同：连续 Raw 多通道 EEG 电位（V）；epoch_duration 用于内部检测分窗，频带和时长足够。

输出合同：data=原波形副本。

### EEG-BRIDGE-REPAIR / bridge_repair

输入 `raw`；状态效应 `preserve`；模型 `None`；拟合 `False`；显式决定 `True`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "bridged_idx",
    "bad_limit"
  ],
  "properties": {
    "bridged_idx": {
      "type": "array"
    },
    "bad_limit": {
      "type": "integer"
    }
  }
}
```

输入合同：Raw 电位（V）；同一输入上确认的桥接对，有效 EEG 坐标。

输出合同：data=修复后的 Raw；空间结构和秩可能改变。

### EEG-INTERPOLATE / interpolate

输入 `either`；状态效应 `mark`；模型 `None`；拟合 `False`；显式决定 `False`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "max_fraction",
    "origin"
  ],
  "properties": {
    "max_fraction": {
      "type": "number",
      "minimum": 0,
      "maximum": 1
    },
    "origin": {
      "type": [
        "array",
        "string"
      ]
    }
  }
}
```

输入合同：Raw 或已加载 Epochs，电位 V；正常供体及待插值 EEG 的位置已确定。interpolate/spherical 至少4个好EEG；interpolate_native 使用原生 MNE 几何/通道可解性条件。 trial_interpolate仅接受已加载有限Epochs；全部EEG坐标有效，全局EEG bads已合入逐Trial固定掩码并清空，每Trial至少4个好EEG。

输出合同：data 为插值后同类型信号；interpolate/spherical 保留原 bads。interpolate_native 默认清除已修复 EEG 标记，reset_bads=False 时保留；辅助坏道不修复且保留。 trial_interpolate保持Trial数、events、selection、ID及掩码外样点，保留输入辅助坏道标记。

### EEG-INTERPOLATE / spherical

输入 `either`；状态效应 `mark`；模型 `None`；拟合 `False`；显式决定 `True`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "bad_channels",
    "origin",
    "kernel",
    "regularization",
    "stiffness",
    "terms",
    "max_fraction"
  ],
  "properties": {
    "bad_channels": {
      "type": "array"
    },
    "origin": {
      "type": [
        "array",
        "string"
      ]
    },
    "kernel": {
      "type": [
        "string",
        "array"
      ],
      "enum": [
        "perrin",
        "eeglab"
      ]
    },
    "regularization": {
      "type": "number"
    },
    "stiffness": {
      "type": "number"
    },
    "terms": {
      "type": "integer",
      "exclusiveMinimum": 0
    },
    "max_fraction": {
      "type": "number",
      "minimum": 0,
      "maximum": 1
    }
  }
}
```

输入合同：Raw 或已加载 Epochs，电位 V；正常供体及待插值 EEG 的位置已确定。interpolate/spherical 至少4个好EEG；interpolate_native 使用原生 MNE 几何/通道可解性条件。 trial_interpolate仅接受已加载有限Epochs；全部EEG坐标有效，全局EEG bads已合入逐Trial固定掩码并清空，每Trial至少4个好EEG。

输出合同：data 为插值后同类型信号；interpolate/spherical 保留原 bads。interpolate_native 默认清除已修复 EEG 标记，reset_bads=False 时保留；辅助坏道不修复且保留。 trial_interpolate保持Trial数、events、selection、ID及掩码外样点，保留输入辅助坏道标记。

### EEG-INTERPOLATE / interpolate_native

输入 `raw`；状态效应 `mark`；模型 `None`；拟合 `False`；显式决定 `False`。

依赖：`{"pyprep": "0.7.1"}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [],
  "properties": {
    "source_profile": {
      "type": "string",
      "default": "pyprep_071"
    },
    "origin": {
      "type": [
        "array",
        "string"
      ],
      "default": "auto"
    },
    "reset_bads": {
      "type": "boolean",
      "default": true
    },
    "nonfinite": {
      "type": "string",
      "default": "propagate",
      "enum": [
        "reject",
        "propagate"
      ]
    }
  }
}
```

输入合同：Raw 或已加载 Epochs，电位 V；正常供体及待插值 EEG 的位置已确定。interpolate/spherical 至少4个好EEG；interpolate_native 使用原生 MNE 几何/通道可解性条件。 trial_interpolate仅接受已加载有限Epochs；全部EEG坐标有效，全局EEG bads已合入逐Trial固定掩码并清空，每Trial至少4个好EEG。

输出合同：data 为插值后同类型信号；interpolate/spherical 保留原 bads。interpolate_native 默认清除已修复 EEG 标记，reset_bads=False 时保留；辅助坏道不修复且保留。 trial_interpolate保持Trial数、events、selection、ID及掩码外样点，保留输入辅助坏道标记。

### EEG-INTERPOLATE / trial_interpolate

输入 `epochs`；状态效应 `preserve`；模型 `None`；拟合 `False`；显式决定 `True`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "mask",
    "trial_ids",
    "decision_id"
  ],
  "properties": {
    "mask": {
      "type": "array"
    },
    "trial_ids": {
      "type": "array",
      "runtime_binding": "$trial_ids"
    },
    "decision_id": {
      "type": "string"
    },
    "max_fraction": {
      "type": "number",
      "default": 0.1,
      "minimum": 0,
      "maximum": 1
    },
    "origin": {
      "type": [
        "array",
        "string"
      ],
      "default": "auto"
    }
  }
}
```

输入合同：Raw 或已加载 Epochs，电位 V；正常供体及待插值 EEG 的位置已确定。interpolate/spherical 至少4个好EEG；interpolate_native 使用原生 MNE 几何/通道可解性条件。 trial_interpolate仅接受已加载有限Epochs；全部EEG坐标有效，全局EEG bads已合入逐Trial固定掩码并清空，每Trial至少4个好EEG。

输出合同：data 为插值后同类型信号；interpolate/spherical 保留原 bads。interpolate_native 默认清除已修复 EEG 标记，reset_bads=False 时保留；辅助坏道不修复且保留。 trial_interpolate保持Trial数、events、selection、ID及掩码外样点，保留输入辅助坏道标记。

### EEG-EPOCH / epoch

输入 `raw`；状态效应 `epoch`；模型 `None`；拟合 `False`；显式决定 `False`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "events",
    "event_id",
    "tmin",
    "tmax",
    "picks"
  ],
  "properties": {
    "events": {
      "type": "array",
      "runtime_binding": "$events"
    },
    "event_id": {
      "type": "object"
    },
    "tmin": {
      "type": "number"
    },
    "tmax": {
      "type": "number"
    },
    "picks": {
      "type": "array"
    }
  }
}
```

输入合同：Raw 电位（V）；events/event_id已绑定原Trial，picks为唯一已有通道名，可同时保留EEG和EOG等辅助通道。

输出合同：data=所选通道的Epochs，保留EEG/辅助类型、原事件索引及drop_log；无默认baseline/detrend。

### EEG-EPOCH / epoch_with_nonfinite

输入 `raw`；状态效应 `epoch`；模型 `None`；拟合 `False`；显式决定 `False`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "events",
    "event_id",
    "tmin",
    "tmax",
    "picks"
  ],
  "properties": {
    "events": {
      "type": "array",
      "runtime_binding": "$events"
    },
    "event_id": {
      "type": "object"
    },
    "tmin": {
      "type": "number"
    },
    "tmax": {
      "type": "number"
    },
    "picks": {
      "type": "array"
    }
  }
}
```

输入合同：Raw 电位（V）；events/event_id已绑定原Trial，picks为唯一已有通道名，可同时保留EEG和EOG等辅助通道。

输出合同：data=所选通道的Epochs，保留EEG/辅助类型、原事件索引及drop_log；无默认baseline/detrend。

### EEG-TRIAL-REJECT / reject_trials

输入 `epochs`；状态效应 `trials`；模型 `None`；拟合 `False`；显式决定 `False`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "reject",
    "flat",
    "max_fraction"
  ],
  "properties": {
    "reject": {
      "type": [
        "object",
        "null"
      ]
    },
    "flat": {
      "type": [
        "number",
        "object",
        "null"
      ]
    },
    "max_fraction": {
      "type": "number",
      "minimum": 0,
      "maximum": 1
    }
  }
}
```

输入合同：预加载电位 Epochs（V），保留原 selection/drop_log。

输出合同：data=保留Epochs；removed为当前输入Trial位置，removed_selection另存原selection；drop_mask同时返回Trial ID。

### EEG-TRIAL-REJECT / drop_mask

输入 `epochs`；状态效应 `trials`；模型 `None`；拟合 `False`；显式决定 `True`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "reject_mask",
    "trial_ids",
    "decision_id"
  ],
  "properties": {
    "reject_mask": {
      "type": "array"
    },
    "trial_ids": {
      "type": "array",
      "runtime_binding": "$trial_ids"
    },
    "decision_id": {
      "type": "string"
    }
  }
}
```

输入合同：预加载电位 Epochs（V），保留原 selection/drop_log。

输出合同：data=保留Epochs；removed为当前输入Trial位置，removed_selection另存原selection；drop_mask同时返回Trial ID。

### EEG-BASELINE / baseline

输入 `epochs`；状态效应 `preserve`；模型 `None`；拟合 `False`；显式决定 `False`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "baseline"
  ],
  "properties": {
    "baseline": {
      "type": [
        "array",
        "null"
      ]
    }
  }
}
```

输入合同：电位 Epochs（V）；任务支持真实基线窗，伪迹校正已完成。

输出合同：data=同形 Epochs；逐 Epoch、逐通道减去基线均值。

### EEG-ZAPLINE / zapline_plus

输入 `raw`；状态效应 `preserve`；模型 `None`；拟合 `False`；显式决定 `False`。

依赖：`{}`；资产：`['source_root', 'octave_path']`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "source_root",
    "octave_path",
    "picks",
    "noise_frequencies",
    "chunk_seconds",
    "min_chunk_seconds",
    "prominence_quantile",
    "chunk_filter_order",
    "adaptive_sigma",
    "fixed_remove",
    "sigma",
    "min_sigma",
    "max_sigma",
    "detection_width",
    "spectrum_window_seconds",
    "timeout_seconds"
  ],
  "properties": {
    "source_root": {
      "type": "string"
    },
    "octave_path": {
      "type": "string"
    },
    "picks": {
      "type": "array"
    },
    "noise_frequencies": {
      "type": [
        "array",
        "string"
      ]
    },
    "chunk_seconds": {
      "type": "number"
    },
    "min_chunk_seconds": {
      "type": "number"
    },
    "prominence_quantile": {
      "type": "number",
      "minimum": 0,
      "maximum": 1
    },
    "chunk_filter_order": {
      "type": "integer"
    },
    "adaptive_sigma": {
      "type": "boolean"
    },
    "fixed_remove": {
      "type": "integer"
    },
    "sigma": {
      "type": "number"
    },
    "min_sigma": {
      "type": "number"
    },
    "max_sigma": {
      "type": "number"
    },
    "detection_width": {
      "type": "number"
    },
    "spectrum_window_seconds": {
      "type": "number"
    },
    "timeout_seconds": {
      "type": "number",
      "exclusiveMinimum": 0
    }
  }
}
```

输入合同：连续 MNE Raw，整数 sfreq>120 Hz，≥5 个未标坏 EEG picks，时长≥16秒；采集断点先拆段。

输出合同：同形 Raw 副本，仅更新 picks；保留辅助道、时间和事件。

### EEG-BAD-CHANNEL-ENSEMBLE / prep_detect

输入 `raw`；状态效应 `preserve`；模型 `None`；拟合 `False`；显式决定 `False`。

依赖：`{"pyprep": "0.7.1"}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [],
  "properties": {
    "do_detrend": {
      "type": "boolean",
      "default": true
    },
    "matlab_strict": {
      "type": "boolean",
      "default": true
    },
    "random_state": {
      "type": [
        "integer",
        "object",
        "null"
      ],
      "default": 0
    },
    "reject_by_annotation": {
      "type": [
        "string",
        "null"
      ],
      "default": null
    },
    "retained_bandwidth_policy": {
      "type": "string",
      "default": "require",
      "enum": [
        "require",
        "author_attenuated"
      ]
    },
    "criteria": {
      "type": "object",
      "default": {
        "deviation": {
          "deviation_threshold": 5.0
        },
        "hfnoise": {
          "HF_zscore_threshold": 5.0
        },
        "correlation": {
          "correlation_secs": 1.0,
          "correlation_threshold": 0.4,
          "frac_bad": 0.01
        },
        "snr": {},
        "ransac": {
          "n_samples": 50,
          "sample_prop": 0.25,
          "corr_thresh": 0.75,
          "frac_bad": 0.4,
          "corr_window_secs": 5.0,
          "channel_wise": false,
          "max_chunk_size": null
        }
      }
    }
  }
}
```

输入合同：Raw 电位 V；native 检测副本接受 NaN，由作者构造器识别 NaN/平道/人工坏道；Inf 拒绝。

输出合同：原数据、通道、bads 和事件保持；返回独立副本。

### EEG-BAD-CHANNEL-ENSEMBLE / prep_detect_native

输入 `raw`；状态效应 `preserve`；模型 `None`；拟合 `False`；显式决定 `False`。

依赖：`{"pyprep": "0.7.1"}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [],
  "properties": {
    "do_detrend": {
      "type": "boolean",
      "default": true
    },
    "random_state": {
      "type": [
        "integer",
        "object",
        "null"
      ],
      "default": null
    },
    "reject_by_annotation": {
      "type": [
        "string",
        "null"
      ],
      "default": null
    },
    "ransac": {
      "type": "boolean",
      "default": true
    },
    "channel_wise": {
      "type": "boolean",
      "default": false
    },
    "max_chunk_size": {
      "type": [
        "integer",
        "null"
      ],
      "default": null
    },
    "correlation": {
      "type": "boolean",
      "default": true
    },
    "criteria": {
      "type": "object",
      "default": {}
    }
  }
}
```

输入合同：Raw 电位 V；native 检测副本接受 NaN，由作者构造器识别 NaN/平道/人工坏道；Inf 拒绝。

输出合同：原数据、通道、bads 和事件保持；返回独立副本。

### EEG-BAD-CHANNEL-DEVIATION / deviation_detect

输入 `raw`；状态效应 `preserve`；模型 `None`；拟合 `False`；显式决定 `False`。

依赖：`{"pyprep": "0.7.1"}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [],
  "properties": {
    "do_detrend": {
      "type": "boolean",
      "default": true
    },
    "matlab_strict": {
      "type": "boolean",
      "default": true
    },
    "random_state": {
      "type": [
        "integer",
        "object",
        "null"
      ],
      "default": 0
    },
    "reject_by_annotation": {
      "type": [
        "string",
        "null"
      ],
      "default": null
    },
    "deviation_threshold": {
      "type": "number",
      "default": 5.0
    }
  }
}
```

输入合同：Raw EEG（V）；已知坏道固定；检测不变更参考。

输出合同：原数据、通道、bads 和事件保持；返回独立副本。

### EEG-BAD-CHANNEL-CORRELATION / correlation_detect

输入 `raw`；状态效应 `preserve`；模型 `None`；拟合 `False`；显式决定 `False`。

依赖：`{"pyprep": "0.7.1"}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [],
  "properties": {
    "do_detrend": {
      "type": "boolean",
      "default": true
    },
    "matlab_strict": {
      "type": "boolean",
      "default": true
    },
    "random_state": {
      "type": [
        "integer",
        "object",
        "null"
      ],
      "default": 0
    },
    "reject_by_annotation": {
      "type": [
        "string",
        "null"
      ],
      "default": null
    },
    "correlation_secs": {
      "type": "number",
      "default": 1.0
    },
    "correlation_threshold": {
      "type": "number",
      "default": 0.4,
      "minimum": 0,
      "maximum": 1
    },
    "frac_bad": {
      "type": "number",
      "default": 0.01,
      "minimum": 0,
      "maximum": 1
    }
  }
}
```

输入合同：Raw EEG（V）；已知坏道固定；检测不变更参考。

输出合同：原数据、通道、bads 和事件保持；返回独立副本。

### EEG-BAD-CHANNEL-HF-RATIO / hf_ratio_detect

输入 `raw`；状态效应 `preserve`；模型 `None`；拟合 `False`；显式决定 `False`。

依赖：`{"pyprep": "0.7.1"}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [],
  "properties": {
    "do_detrend": {
      "type": "boolean",
      "default": true
    },
    "matlab_strict": {
      "type": "boolean",
      "default": true
    },
    "random_state": {
      "type": [
        "integer",
        "object",
        "null"
      ],
      "default": 0
    },
    "reject_by_annotation": {
      "type": [
        "string",
        "null"
      ],
      "default": null
    },
    "HF_zscore_threshold": {
      "type": "number",
      "default": 5.0
    }
  }
}
```

输入合同：Raw EEG（V）；已知坏道固定；检测不变更参考。

输出合同：原数据、通道、bads 和事件保持；返回独立副本。

### EEG-BAD-CHANNEL-LINE-NOISE / line_noise_detect

输入 `raw`；状态效应 `preserve`；模型 `None`；拟合 `False`；显式决定 `False`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [],
  "properties": {
    "window_s": {
      "type": "number",
      "default": 4.0,
      "exclusiveMinimum": 0
    },
    "stride_s": {
      "type": "number",
      "default": 2.0,
      "exclusiveMinimum": 0
    },
    "tail": {
      "type": "string",
      "default": "drop",
      "enum": [
        "drop"
      ]
    },
    "valid_intervals": {
      "type": [
        "array",
        "null"
      ],
      "default": null
    },
    "min_windows": {
      "type": "integer",
      "default": 1,
      "exclusiveMinimum": 0
    },
    "line_bands_Hz": {
      "type": "array",
      "default": [
        [
          49.0,
          51.0
        ]
      ]
    },
    "background_bands_Hz": {
      "type": "array",
      "default": [
        [
          40.0,
          48.0
        ],
        [
          52.0,
          60.0
        ]
      ]
    },
    "welch_segment_s": {
      "type": "number",
      "default": 2.0
    },
    "overlap_fraction": {
      "type": "number",
      "default": 0.5,
      "minimum": 0,
      "maximum": 1
    },
    "n_fft": {
      "type": [
        "integer",
        "null"
      ],
      "default": null
    },
    "ratio_threshold": {
      "type": "number",
      "default": 5.0
    },
    "frac_bad": {
      "type": "number",
      "default": 0.25,
      "minimum": 0,
      "maximum": 1
    }
  }
}
```

输入合同：Raw EEG（V）；工频/背景带明确且互不重叠，均低于 Nyquist。

输出合同：原数据、通道、bads 和事件保持；返回独立副本。

### EEG-ICLABEL / iclabel_assess

输入 `either`；状态效应 `preserve`；模型 `ica`；拟合 `False`；显式决定 `False`。

依赖：`{"mne-icalabel": "0.8.1"}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "reference_id"
  ],
  "properties": {
    "reference_id": {
      "type": "string",
      "runtime_binding": "$reference_id"
    },
    "backend": {
      "type": "string",
      "default": "torch",
      "enum": [
        "torch",
        "onnx"
      ]
    }
  }
}
```

输入合同：与ICA通道、参考和投影状态兼容的Raw/Epochs电位（V），全部ICA通道有坐标；平均参考投影须先应用。评估实际CAR残差；参考名或custom_ref_applied不能代替数据核验。

输出合同：波形及 ICA model 保持，输出完整 IC×7 概率。

### EEG-MARA / mara_assess

输入 `either`；状态效应 `preserve`；模型 `ica`；拟合 `False`；显式决定 `False`。

依赖：`{}`；资产：`['source_root', 'octave']`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "source_root",
    "reference_id"
  ],
  "properties": {
    "source_root": {
      "type": "string"
    },
    "reference_id": {
      "type": "string",
      "runtime_binding": "$reference_id"
    },
    "octave": {
      "type": "string",
      "default": "octave"
    },
    "timeout": {
      "type": "number",
      "default": 180.0,
      "exclusiveMinimum": 0
    }
  }
}
```

输入合同：Raw/Epochs 电位（V）和兼容 ICA（noise_cov=None）；标准头皮通道名、MNE head 坐标；≥30秒信号，采样率≥100 Hz、低通≥40 Hz。

输出合同：波形与 ICA model 保持；返回每 IC 的伪迹后验、六个标准化特征及候选。

### EEG-ADJUST / adjust_assess

输入 `epochs`；状态效应 `preserve`；模型 `ica`；拟合 `False`；显式决定 `False`。

依赖：`{}`；资产：`['source_root', 'octave']`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "source_root",
    "reference_id"
  ],
  "properties": {
    "source_root": {
      "type": "string"
    },
    "reference_id": {
      "type": "string",
      "runtime_binding": "$reference_id"
    },
    "octave": {
      "type": "string",
      "default": "octave"
    },
    "timeout": {
      "type": "number",
      "default": 180.0,
      "exclusiveMinimum": 0
    },
    "xyz_scale": {
      "type": "number",
      "default": 1000.0
    }
  }
}
```

输入合同：已加载 Epochs 电位（V）及兼容 ICA（noise_cov=None）；至少2个Epoch、4个IC、11个好电极，MNE head 坐标覆盖左右眼区、额区与后区。

输出合同：波形与 ICA model 保持；返回眼动、眨眼、间断伪迹的候选和实际 EM 阈值。

### EEG-FASTER-IC / faster_ic_assess

输入 `epochs`；状态效应 `preserve`；模型 `ica`；拟合 `False`；显式决定 `False`。

依赖：`{"mne-faster": "1.2.2"}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "reference_id"
  ],
  "properties": {
    "reference_id": {
      "type": "string",
      "runtime_binding": "$reference_id"
    },
    "metrics": {
      "type": "array",
      "default": [
        "eog_correlation",
        "kurtosis",
        "power_gradient",
        "hurst",
        "median_gradient"
      ]
    },
    "threshold": {
      "type": [
        "number",
        "string"
      ],
      "default": 3.0
    },
    "max_iter": {
      "type": [
        "integer",
        "string"
      ],
      "default": 1
    },
    "power_range_Hz": {
      "type": [
        "array",
        "null"
      ],
      "default": null
    }
  }
}
```

输入合同：已加载 Epochs（V）与对应 ICA 模型；通道、参考、采样率一致；EOG 指标需要 EOG 类型通道。

输出合同：数据和 ICA 模型保持；返回独立副本。

### EEG-SASICA / sasica_assess

输入 `either`；状态效应 `preserve`；模型 `ica`；拟合 `False`；显式决定 `False`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "reference_id",
    "criteria"
  ],
  "properties": {
    "reference_id": {
      "type": "string",
      "runtime_binding": "$reference_id"
    },
    "criteria": {
      "type": "object"
    },
    "external_assessments": {
      "type": "object",
      "default": {}
    },
    "review": {
      "type": [
        "object",
        "null"
      ],
      "default": null
    }
  }
}
```

输入合同：Raw/Epochs（V）与对应 ICA 模型；trialfoc/SNR 需要 Epochs；相关指标显式指定辅助通道；参考与模型身份固定。

输出合同：数据和 ICA 模型保持；返回独立副本。

### EEG-ASR / asr_fit

输入 `raw`；状态效应 `model`；模型 `asr`；拟合 `True`；显式决定 `False`。

依赖：`{"asrpy": "0.0.8"}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "scope",
    "reference_id",
    "start",
    "stop"
  ],
  "properties": {
    "scope": {
      "type": "object",
      "runtime_binding": "$scope"
    },
    "reference_id": {
      "type": "string",
      "runtime_binding": "$reference_id"
    },
    "start": {
      "type": "integer"
    },
    "stop": {
      "type": "integer",
      "runtime_binding": "$n_samples"
    },
    "cutoff": {
      "type": "number",
      "default": 20.0
    },
    "blocksize": {
      "type": "integer",
      "default": 100,
      "exclusiveMinimum": 0
    },
    "win_len": {
      "type": "number",
      "default": 0.5,
      "exclusiveMinimum": 0
    },
    "win_overlap": {
      "type": "number",
      "default": 0.66,
      "minimum": 0,
      "maximum": 1
    },
    "max_dropout_fraction": {
      "type": "number",
      "default": 0.1,
      "minimum": 0,
      "maximum": 1
    },
    "min_clean_fraction": {
      "type": "number",
      "default": 0.25,
      "minimum": 0,
      "maximum": 1
    },
    "max_bad_chans": {
      "type": "number",
      "default": 0.1,
      "minimum": 0,
      "maximum": 1
    }
  }
}
```

输入合同：连续 EEG 电位（V）、稳定参考；校准副本高通≥0.5 Hz，显式校准区间及自动选择后均≥30 秒。

输出合同：fit 返回校准 model 且保持波形；apply 返回欧氏 ASR correction 同形波形，通道及样点轴保持。

### EEG-ASR / asr_apply

输入 `raw`；状态效应 `preserve`；模型 `asr`；拟合 `False`；显式决定 `False`。

依赖：`{"asrpy": "0.0.8"}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "reference_id"
  ],
  "properties": {
    "reference_id": {
      "type": "string",
      "runtime_binding": "$reference_id"
    },
    "lookahead": {
      "type": "number",
      "default": 0.25,
      "exclusiveMinimum": 0
    },
    "stepsize": {
      "type": "integer",
      "default": 32,
      "exclusiveMinimum": 0
    },
    "maxdims": {
      "type": "number",
      "default": 0.66
    },
    "mem_splits": {
      "type": "integer",
      "default": 1,
      "exclusiveMinimum": 0
    }
  }
}
```

输入合同：连续 EEG 电位（V）、稳定参考；校准副本高通≥0.5 Hz，显式校准区间及自动选择后均≥30 秒。

输出合同：fit 返回校准 model 且保持波形；apply 返回欧氏 ASR correction 同形波形，通道及样点轴保持。

### EEG-WICA / wica_apply

输入 `raw`；状态效应 `preserve`；模型 `ica`；拟合 `False`；显式决定 `True`。

依赖：`{"PyWavelets": "1.8.0"}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "variant",
    "probabilities",
    "component_id",
    "decision_id",
    "reference_id"
  ],
  "properties": {
    "variant": {
      "type": "string",
      "enum": [
        "ordinary",
        "targeted"
      ]
    },
    "probabilities": {
      "type": "array"
    },
    "component_id": {
      "type": "string"
    },
    "decision_id": {
      "type": "string"
    },
    "reference_id": {
      "type": "string",
      "runtime_binding": "$reference_id"
    },
    "thresholds": {
      "type": "array",
      "default": [
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0
      ]
    },
    "clean_other": {
      "type": "string",
      "default": "no"
    },
    "eye_weights": {
      "type": [
        "array",
        "null"
      ],
      "default": null
    },
    "extra_eye": {
      "type": [
        "array",
        "null"
      ],
      "default": null
    },
    "line_freq": {
      "type": [
        "number",
        "null"
      ],
      "default": null
    },
    "muscle_slope": {
      "type": "number",
      "default": -0.31
    }
  }
}
```

输入合同：连续 EEG 电位（V）、冻结的 MNE ICA（noise_cov=None）、绑定 component_id 的 IC×7 概率；targeted 另需逐 IC×样点的最终 Eye 平滑权重和决定来源。

输出合同：同形校正波形和原 ICA model；按 EEGLAB 未减均值激活保留原成分、移除成分及校正成分。

### EEG-CCA / cca_fit

输入 `raw`；状态效应 `model`；模型 `cca`；拟合 `True`；显式决定 `False`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "scope",
    "reference_id"
  ],
  "properties": {
    "scope": {
      "type": "object",
      "runtime_binding": "$scope"
    },
    "reference_id": {
      "type": "string",
      "runtime_binding": "$reference_id"
    },
    "lags": {
      "type": "integer",
      "default": 1,
      "exclusiveMinimum": 0
    }
  }
}
```

输入合同：连续 EEG 电位（V），好 EEG 及参考稳定，原/延迟协方差满秩；成分排除由独立决定提供。

输出合同：fit 保持波形并返回 CCA model；apply 返回同形校正波形和原 model。

### EEG-CCA / cca_apply

输入 `raw`；状态效应 `preserve`；模型 `cca`；拟合 `False`；显式决定 `True`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "exclude",
    "reference_id",
    "decision_id"
  ],
  "properties": {
    "exclude": {
      "type": "array"
    },
    "reference_id": {
      "type": "string",
      "runtime_binding": "$reference_id"
    },
    "decision_id": {
      "type": "string"
    }
  }
}
```

输入合同：连续 EEG 电位（V），好 EEG 及参考稳定，原/延迟协方差满秩；成分排除由独立决定提供。

输出合同：fit 保持波形并返回 CCA model；apply 返回同形校正波形和原 model。

### EEG-MWF / mwf_fit

输入 `raw`；状态效应 `model`；模型 `mwf`；拟合 `True`；显式决定 `False`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "mask",
    "scope",
    "reference_id",
    "mask_id"
  ],
  "properties": {
    "mask": {
      "type": "array"
    },
    "scope": {
      "type": "object",
      "runtime_binding": "$scope"
    },
    "reference_id": {
      "type": "string",
      "runtime_binding": "$reference_id"
    },
    "mask_id": {
      "type": "string"
    },
    "delay": {
      "type": "integer",
      "default": 0
    },
    "delay_spacing": {
      "type": "integer",
      "default": 1,
      "exclusiveMinimum": 0
    },
    "singlesided": {
      "type": "boolean",
      "default": false
    },
    "rank": {
      "type": [
        "string",
        "integer"
      ],
      "default": "poseig",
      "enum": [
        "poseig",
        "full",
        "pct",
        "first"
      ]
    },
    "rankopt": {
      "type": [
        "number",
        "integer"
      ],
      "default": 1
    },
    "treatnans": {
      "type": "string",
      "default": "ignore"
    },
    "mu": {
      "type": "number",
      "default": 1.0
    }
  }
}
```

输入合同：连续 EEG 电位（V）、逐样点伪迹 mask（1=伪迹、0=干净、NaN=按策略），两类样点足以估计延迟协方差。

输出合同：fit 保持波形并返回 MWF model；apply 返回同形校正波形及原 model。

### EEG-MWF / mwf_apply

输入 `raw`；状态效应 `preserve`；模型 `mwf`；拟合 `False`；显式决定 `False`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "reference_id"
  ],
  "properties": {
    "reference_id": {
      "type": "string",
      "runtime_binding": "$reference_id"
    }
  }
}
```

输入合同：连续 EEG 电位（V）、逐样点伪迹 mask（1=伪迹、0=干净、NaN=按策略），两类样点足以估计延迟协方差。

输出合同：fit 保持波形并返回 MWF model；apply 返回同形校正波形及原 model。

### EEG-AUTOREJECT / autoreject_fit

输入 `epochs`；状态效应 `model`；模型 `autoreject`；拟合 `True`；显式决定 `False`。

依赖：`{"autoreject": "0.5.0"}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "mode",
    "scope",
    "reference_id",
    "trial_ids",
    "cv"
  ],
  "properties": {
    "mode": {
      "type": "string",
      "enum": [
        "global",
        "local"
      ]
    },
    "scope": {
      "type": "object",
      "runtime_binding": "$scope"
    },
    "reference_id": {
      "type": "string",
      "runtime_binding": "$reference_id"
    },
    "trial_ids": {
      "type": "array",
      "runtime_binding": "$trial_ids"
    },
    "cv": {
      "type": "array"
    },
    "seed": {
      "type": "integer",
      "default": 0
    },
    "n_interpolate": {
      "type": "array",
      "default": [
        1,
        4
      ]
    },
    "consensus": {
      "type": "array",
      "default": [
        0.5,
        0.75,
        1.0
      ]
    },
    "thresh_method": {
      "type": "string",
      "default": "bayesian_optimization",
      "enum": [
        "bayesian_optimization",
        "random_search"
      ]
    }
  }
}
```

输入合同：已加载 Epochs 电位（V）、Trial ID、参考和实际 CV 划分；local 坐标可插值，拟合限训练/校准集合。

输出合同：fit 保持波形并返回 global/local model；apply 按固定模型拒绝或局部插值后拒绝 Epoch，返回剩余 Trial。

### EEG-AUTOREJECT / autoreject_apply

输入 `epochs`；状态效应 `trials`；模型 `autoreject`；拟合 `False`；显式决定 `False`。

依赖：`{"autoreject": "0.5.0"}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "reference_id",
    "trial_ids"
  ],
  "properties": {
    "reference_id": {
      "type": "string",
      "runtime_binding": "$reference_id"
    },
    "trial_ids": {
      "type": "array",
      "runtime_binding": "$trial_ids"
    }
  }
}
```

输入合同：已加载 Epochs 电位（V）、Trial ID、参考和实际 CV 划分；local 坐标可插值，拟合限训练/校准集合。

输出合同：fit 保持波形并返回 global/local model；apply 按固定模型拒绝或局部插值后拒绝 Epoch，返回剩余 Trial。

### EEG-REGRESSION-BASELINE / regression_baseline_fit

输入 `array`；状态效应 `model`；模型 `regression_baseline`；拟合 `True`；显式决定 `False`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "scope",
    "axes",
    "times",
    "baseline",
    "factors",
    "factor_names"
  ],
  "properties": {
    "scope": {
      "type": "object",
      "runtime_binding": "$scope"
    },
    "axes": {
      "type": "array",
      "runtime_binding": "$axes"
    },
    "times": {
      "type": "array",
      "runtime_binding": "$times"
    },
    "baseline": {
      "type": [
        "array",
        "null"
      ]
    },
    "factors": {
      "type": "array"
    },
    "factor_names": {
      "type": "array"
    }
  }
}
```

输入合同：主入口为 MNE Epochs 与 picks EEG 通道名，辅助道保留；数组入口为 N×C×T 波形；axes 通道名，times 秒轴。fit 的 factors 为 N×0/1/2，以 -1/+1 编码；基线区间在时间轴内。

输出合同：主入口返回 Epochs 并保留 events/times/channels/selection；数组入口返回 N×C×T 校正波形及冻结回归模型；仅减去基线协变量贡献，保留条件和截距项。

### EEG-REGRESSION-BASELINE / regression_baseline_apply

输入 `array`；状态效应 `preserve`；模型 `regression_baseline`；拟合 `False`；显式决定 `False`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "axes",
    "times",
    "trial_ids"
  ],
  "properties": {
    "axes": {
      "type": "array",
      "runtime_binding": "$axes"
    },
    "times": {
      "type": "array",
      "runtime_binding": "$times"
    },
    "trial_ids": {
      "type": "array",
      "runtime_binding": "$trial_ids"
    }
  }
}
```

输入合同：主入口为 MNE Epochs 与 picks EEG 通道名，辅助道保留；数组入口为 N×C×T 波形；axes 通道名，times 秒轴。fit 的 factors 为 N×0/1/2，以 -1/+1 编码；基线区间在时间轴内。

输出合同：主入口返回 Epochs 并保留 events/times/channels/selection；数组入口返回 N×C×T 校正波形及冻结回归模型；仅减去基线协变量贡献，保留条件和截距项。

### EEG-REGRESSION-BASELINE / regression_baseline_epochs_fit

输入 `epochs`；状态效应 `model`；模型 `regression_baseline_epochs`；拟合 `True`；显式决定 `False`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "scope",
    "picks",
    "baseline",
    "factors",
    "factor_names"
  ],
  "properties": {
    "scope": {
      "type": "object",
      "runtime_binding": "$scope"
    },
    "picks": {
      "type": "array"
    },
    "baseline": {
      "type": [
        "array",
        "null"
      ]
    },
    "factors": {
      "type": "array"
    },
    "factor_names": {
      "type": "array"
    }
  }
}
```

输入合同：主入口为 MNE Epochs 与 picks EEG 通道名，辅助道保留；数组入口为 N×C×T 波形；axes 通道名，times 秒轴。fit 的 factors 为 N×0/1/2，以 -1/+1 编码；基线区间在时间轴内。

输出合同：主入口返回 Epochs 并保留 events/times/channels/selection；数组入口返回 N×C×T 校正波形及冻结回归模型；仅减去基线协变量贡献，保留条件和截距项。

### EEG-REGRESSION-BASELINE / regression_baseline_epochs_apply

输入 `epochs`；状态效应 `preserve`；模型 `regression_baseline_epochs`；拟合 `False`；显式决定 `False`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "picks",
    "trial_ids"
  ],
  "properties": {
    "picks": {
      "type": "array"
    },
    "trial_ids": {
      "type": "array",
      "runtime_binding": "$trial_ids"
    }
  }
}
```

输入合同：主入口为 MNE Epochs 与 picks EEG 通道名，辅助道保留；数组入口为 N×C×T 波形；axes 通道名，times 秒轴。fit 的 factors 为 N×0/1/2，以 -1/+1 编码；基线区间在时间轴内。

输出合同：主入口返回 Epochs 并保留 events/times/channels/selection；数组入口返回 N×C×T 校正波形及冻结回归模型；仅减去基线协变量贡献，保留条件和截距项。

### EEG-WINDOW-MAD / window_mad

输入 `epochs`；状态效应 `preserve`；模型 `None`；拟合 `False`；显式决定 `False`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [],
  "properties": {
    "mad_multiplier": {
      "type": "number",
      "default": 25.0
    },
    "flat_limit_V": {
      "type": "number",
      "default": 2e-06
    },
    "blink_upper_bound_V": {
      "type": [
        "array",
        "null"
      ],
      "default": null
    }
  }
}
```

输入合同：诊断Epochs（V），窗口及原样点映射由上游固定；window_mad可传逐通道眨眼上界。blink_upper_bound要求非空有限诊断Epochs；可选blink_epochs须非空有限，并与诊断Epochs具有相同道序、类型、采样率、每窗样点数及坏道状态。

输出合同：原数据、通道、bads 和事件保持；返回独立副本。；blink_upper_bound 返回上界及 detected_blink_epochs / diagnostic_upper_tail 模式。

### EEG-WINDOW-MAD / blink_upper_bound

输入 `epochs`；状态效应 `preserve`；模型 `None`；拟合 `False`；显式决定 `False`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [],
  "properties": {
    "blink_epochs": {
      "type": [
        "object",
        "null"
      ],
      "default": null
    },
    "mad_multiplier": {
      "type": "number",
      "default": 10.0
    },
    "fallback_percentile": {
      "type": "number",
      "default": 80.0,
      "minimum": 0,
      "maximum": 100
    }
  }
}
```

输入合同：诊断Epochs（V），窗口及原样点映射由上游固定；window_mad可传逐通道眨眼上界。blink_upper_bound要求非空有限诊断Epochs；可选blink_epochs须非空有限，并与诊断Epochs具有相同道序、类型、采样率、每窗样点数及坏道状态。

输出合同：原数据、通道、bads 和事件保持；返回独立副本。；blink_upper_bound 返回上界及 detected_blink_epochs / diagnostic_upper_tail 模式。

### EEG-SPECTRAL-SLOPE / spectral_slope

输入 `either`；状态效应 `preserve`；模型 `None`；拟合 `False`；显式决定 `False`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [],
  "properties": {
    "mode": {
      "type": "string",
      "default": "fieldtrip_mtmfft",
      "enum": [
        "fieldtrip_mtmfft",
        "relax_ic_welch"
      ]
    },
    "frequencies_Hz": {
      "type": "array",
      "default": [
        1,
        2,
        3,
        4,
        5,
        6,
        7,
        8,
        9,
        10,
        11,
        12,
        13,
        14,
        15,
        16,
        17,
        18,
        19,
        20,
        21,
        22,
        23,
        24,
        25,
        26,
        27,
        28,
        29,
        30,
        31,
        32,
        33,
        34,
        35,
        36,
        37,
        38,
        39,
        40,
        41,
        42,
        43,
        44,
        45,
        46,
        47,
        48,
        49,
        50,
        51,
        52,
        53,
        54,
        55,
        56,
        57,
        58,
        59,
        60,
        61,
        62,
        63,
        64,
        65,
        66,
        67,
        68,
        69,
        70,
        71,
        72,
        73,
        74,
        75
      ]
    },
    "fit_range_Hz": {
      "type": "array",
      "default": [
        7.0,
        75.0
      ]
    },
    "excluded_bands_Hz": {
      "type": "array",
      "default": []
    },
    "slope_threshold": {
      "type": "number",
      "default": -0.31
    },
    "direction": {
      "type": "string",
      "default": "above"
    },
    "picks": {
      "type": [
        "array",
        "null"
      ],
      "default": null
    },
    "retained_bandwidth_policy": {
      "type": "string",
      "default": "require",
      "enum": [
        "require",
        "author_attenuated"
      ]
    }
  }
}
```

输入合同：Raw 或已加载 Epochs 电位 V；频率始终严格位于(0,Nyquist)。retained_bandwidth_policy=require 时拟合上界不得超过实际低通；author_attenuated 允许对已经衰减的频带计算作者斜率并报告该条件。

输出合同：原数据、通道、bads 和事件保持；返回独立副本。

### EEG-EOG-STEP / eog_step

输入 `epochs`；状态效应 `preserve`；模型 `None`；拟合 `False`；显式决定 `False`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [],
  "properties": {
    "channels": {
      "type": [
        "array",
        "null"
      ],
      "default": null
    },
    "search_interval_s": {
      "type": "array",
      "default": [
        -0.2,
        0.3
      ]
    },
    "half_window_s": {
      "type": "number",
      "default": 0.1,
      "exclusiveMinimum": 0
    },
    "threshold_V": {
      "type": "number",
      "default": 3.2e-05
    },
    "statistic": {
      "type": "string",
      "default": "trimmean95",
      "enum": [
        "trimmean95",
        "mean"
      ]
    }
  }
}
```

输入合同：Epochs（V）含辅助 EOG；通道差方向、检测区间与半窗口已指定。

输出合同：原数据、通道、bads 和事件保持；返回独立副本。

### EEG-JOINT-PROBABILITY / joint_probability

输入 `epochs`；状态效应 `preserve`；模型 `None`；拟合 `False`；显式决定 `False`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [],
  "properties": {
    "local_threshold": {
      "type": "number",
      "default": 10.0
    },
    "global_threshold": {
      "type": "number",
      "default": 10.0
    },
    "bins": {
      "type": "integer",
      "default": 1000,
      "exclusiveMinimum": 0
    }
  }
}
```

输入合同：Epochs（V），至少 2 个 Epoch 和每窗 4 点；沿各通道的 Epoch 轴标准化，global 每窗合并通道和时间。

输出合同：原数据、通道、bads 和事件保持；返回独立副本。

### EEG-KURTOSIS / kurtosis

输入 `epochs`；状态效应 `preserve`；模型 `None`；拟合 `False`；显式决定 `False`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [],
  "properties": {
    "local_threshold": {
      "type": "number",
      "default": 10.0
    },
    "global_threshold": {
      "type": "number",
      "default": 10.0
    }
  }
}
```

输入合同：Epochs（V），至少 2 个 Epoch 和每窗 4 点；沿各通道的 Epoch 轴标准化，global 每窗合并通道和时间。

输出合同：原数据、通道、bads 和事件保持；返回独立副本。

### EEG-BLINK-IQR / blink_iqr

输入 `raw`；状态效应 `preserve`；模型 `None`；拟合 `False`；显式决定 `False`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "reference_evidence"
  ],
  "properties": {
    "reference_evidence": {
      "type": "object"
    },
    "blink_channels": {
      "type": "array",
      "default": [
        "Fp1",
        "Fpz",
        "Fp2",
        "AF3",
        "AF4",
        "F3",
        "F1",
        "Fz",
        "F2",
        "F4"
      ]
    },
    "lowpass_Hz": {
      "type": "number",
      "default": 25.0
    },
    "zero_intervals": {
      "type": [
        "array",
        "null"
      ],
      "default": null
    },
    "variant": {
      "type": "string",
      "default": "relax_2_0_1",
      "enum": [
        "relax_2_0_1",
        "repaired_indices"
      ]
    }
  }
}
```

输入合同：连续检测副本（V）：已临时补回原坏道、加入零值初始参考、按完整通道轴平均参考，再恢复检测好道轴。传 reference_evidence 绑定该参考总体；独立于清理输出参考。

输出合同：原数据、通道、bads 和事件保持；返回独立副本。

### EEG-ROBUST-REFERENCE / prep_reference_fit

输入 `raw`；状态效应 `reference_model`；模型 `prep_reference`；拟合 `True`；显式决定 `False`。

依赖：`{"pyprep": "0.7.1"}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "ref_chs",
    "reref_chs"
  ],
  "properties": {
    "ref_chs": {
      "type": "array"
    },
    "reref_chs": {
      "type": "array"
    },
    "max_iterations": {
      "type": "integer",
      "default": 4
    },
    "ransac": {
      "type": "boolean",
      "default": true
    },
    "channel_wise": {
      "type": "boolean",
      "default": false
    },
    "max_chunk_size": {
      "type": [
        "integer",
        "null"
      ],
      "default": null
    },
    "random_state": {
      "type": [
        "integer",
        "object",
        "null"
      ],
      "default": null
    },
    "reject_by_annotation": {
      "type": [
        "string",
        "null"
      ],
      "default": null
    }
  }
}
```

输入合同：仅含 EEG 的 Raw 电位 V，通道坐标及人工坏道已设置；允许 NaN，拒绝 Inf；辅助通道由上游暂存。PyPREP0.7.1、MNE1.10.2。

输出合同：fit 返回参考后的 Raw 和 awaiting_final_interpolation 状态；finalize 返回最终插值/校正参考后的有限 Raw 和 finalized 状态。函数不修改输入或输入模型。

### EEG-ROBUST-REFERENCE / prep_reference_finalize

输入 `raw`；状态效应 `reference`；模型 `prep_reference`；拟合 `False`；显式决定 `False`。

依赖：`{"pyprep": "0.7.1"}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [],
  "properties": {}
}
```

输入合同：仅含 EEG 的 Raw 电位 V，通道坐标及人工坏道已设置；允许 NaN，拒绝 Inf；辅助通道由上游暂存。PyPREP0.7.1、MNE1.10.2。

输出合同：fit 返回参考后的 Raw 和 awaiting_final_interpolation 状态；finalize 返回最终插值/校正参考后的有限 Raw 和 finalized 状态。函数不修改输入或输入模型。

### EEG-IC-BLINK-WEIGHTS / eye_weights

输入 `raw`；状态效应 `preserve`；模型 `ica`；拟合 `False`；显式决定 `False`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "eye_components",
    "raw_blink_mask",
    "component_id",
    "reference_id"
  ],
  "properties": {
    "eye_components": {
      "type": "array"
    },
    "raw_blink_mask": {
      "type": "array"
    },
    "component_id": {
      "type": "string"
    },
    "reference_id": {
      "type": "string",
      "runtime_binding": "$reference_id"
    },
    "profile": {
      "type": "string",
      "default": "relax_2_0_1",
      "enum": [
        "relax_2_0_1",
        "repaired_units_indices"
      ]
    }
  }
}
```

输入合同：Raw 电位 V；匹配通道、采样率、参考及分量指纹的 ICA 模型；noise_cov=None。

输出合同：data=输入副本；eye_weights 为 IC×sample 的 [0,1] 数组，非 Eye IC 行为0。

### EEG-CHANNEL-REJECTION-BUDGET / relax_budget

输入 `raw`；状态效应 `preserve`；模型 `None`；拟合 `False`；显式决定 `False`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "channel_epoch_mask",
    "muscle_slopes",
    "window_starts",
    "window_samples",
    "original_channels"
  ],
  "properties": {
    "channel_epoch_mask": {
      "type": "array"
    },
    "muscle_slopes": {
      "type": "array"
    },
    "window_starts": {
      "type": "array"
    },
    "window_samples": {
      "type": "integer",
      "exclusiveMinimum": 0
    },
    "original_channels": {
      "type": "array"
    },
    "maximum": {
      "type": "number",
      "default": 0.1,
      "minimum": 0,
      "maximum": 1
    },
    "extreme_fraction": {
      "type": "number",
      "default": 0.25,
      "minimum": 0,
      "maximum": 1
    },
    "muscle_fraction": {
      "type": "number",
      "default": 0.5,
      "minimum": 0,
      "maximum": 1
    },
    "muscle_threshold": {
      "type": "number",
      "default": -0.31
    },
    "profile": {
      "type": "string",
      "default": "relax_2_0_1",
      "enum": [
        "relax_2_0_1",
        "repaired_units_indices"
      ]
    }
  }
}
```

输入合同：预加载有限值 Raw，仅含未标坏的当前 EEG；bool 道×窗极端掩码、同轴有限肌电斜率、严格递增的相对样点窗起点及窗长；原始道名唯一并包含当前道名。

输出合同：Raw 副本；极端/肌电坏道名及剩余预算。无删道副作用。

### EEG-MUSCLE-TRIAL-DECISION / relax_muscle_trials

输入 `epochs`；状态效应 `preserve`；模型 `None`；拟合 `False`；显式决定 `False`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "slopes",
    "trial_ids"
  ],
  "properties": {
    "slopes": {
      "type": "array"
    },
    "trial_ids": {
      "type": "array",
      "runtime_binding": "$trial_ids"
    },
    "threshold": {
      "type": [
        "number",
        "string"
      ],
      "default": -0.31
    },
    "maximum": {
      "type": "number",
      "default": 0.5,
      "minimum": 0,
      "maximum": 1
    }
  }
}
```

输入合同：非空预加载有限值 EEG Epochs；有限 slopes 为试次×道；trial_ids 与当前试次一一对应且唯一。 仅含未标坏EEG通道。

输出合同：Epochs 副本及当前试次顺序的 bool 拒绝掩码；拒绝由 EEG-TRIAL-REJECT 执行。

### EEG-AUTO-BAD-CHANNEL / detect_bad_channels

输入 `raw`；状态效应 `preserve`；模型 `None`；拟合 `False`；显式决定 `False`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "adaptation_scope"
  ],
  "properties": {
    "adaptation_scope": {
      "type": "string",
      "enum": [
        "record_unlabeled"
      ]
    },
    "selection_policy": {
      "type": "string",
      "default": "consensus_v2"
    },
    "window_s": {
      "type": "number",
      "default": 1.0,
      "exclusiveMinimum": 0
    },
    "flat_duration_s": {
      "type": "number",
      "default": 5.0
    },
    "flat_ptp_V": {
      "type": "number",
      "default": 1e-07
    },
    "deviation_z": {
      "type": "number",
      "default": 5.0
    },
    "correlation_threshold": {
      "type": "number",
      "default": 0.4,
      "minimum": 0,
      "maximum": 1
    },
    "bad_window_fraction": {
      "type": "number",
      "default": 0.1,
      "minimum": 0,
      "maximum": 1
    },
    "persistent_low_corr_fraction": {
      "type": "number",
      "default": 0.5,
      "minimum": 0,
      "maximum": 1
    },
    "persistent_low_corr_seconds": {
      "type": "number",
      "default": 5.0
    },
    "shared_correlation_threshold": {
      "type": "number",
      "default": 0.7,
      "minimum": 0,
      "maximum": 1
    }
  }
}
```

输入合同：Finite physical V continuous MNE Raw; explicit record_unlabeled scope for statistical adaptation.

输出合同：Same ordered channels, sfreq, first_samp, annotations, sample count; no trial rejection.

### EEG-AUTO-BAD-CHANNEL / interpolate_bad_channels

输入 `raw`；状态效应 `mark`；模型 `None`；拟合 `False`；显式决定 `False`。

依赖：`{}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [],
  "properties": {
    "max_fraction": {
      "type": "number",
      "default": 0.1,
      "minimum": 0,
      "maximum": 1
    }
  }
}
```

输入合同：Finite physical V continuous MNE Raw; explicit record_unlabeled scope for statistical adaptation.

输出合同：Same ordered channels, sfreq, first_samp, annotations, sample count; no trial rejection.

### EEG-ASR-AUTO / asr_clean

输入 `raw`；状态效应 `preserve`；模型 `None`；拟合 `False`；显式决定 `False`。

依赖：`{"asrpy": "0.0.8"}`；资产：`[]`。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "adaptation_scope"
  ],
  "properties": {
    "adaptation_scope": {
      "type": "string",
      "enum": [
        "record_unlabeled"
      ]
    },
    "on_insufficient_calibration": {
      "type": "string",
      "default": "error",
      "enum": [
        "error",
        "identity"
      ]
    },
    "cutoff": {
      "type": "number",
      "default": 20.0
    },
    "win_len": {
      "type": "number",
      "default": 0.5,
      "exclusiveMinimum": 0
    },
    "win_overlap": {
      "type": "number",
      "default": 0.66,
      "minimum": 0,
      "maximum": 1
    },
    "min_clean_seconds": {
      "type": "number",
      "default": 30.0
    },
    "lookahead": {
      "type": "number",
      "default": 0.25,
      "exclusiveMinimum": 0
    },
    "stepsize": {
      "type": "integer",
      "default": 32,
      "exclusiveMinimum": 0
    },
    "maxdims": {
      "type": "number",
      "default": 0.66
    },
    "mem_splits": {
      "type": "integer",
      "default": 3,
      "exclusiveMinimum": 0
    }
  }
}
```

输入合同：Finite physical V continuous MNE Raw; explicit record_unlabeled scope for statistical adaptation.

输出合同：Same ordered channels, sfreq, first_samp, annotations, sample count; no trial rejection.

