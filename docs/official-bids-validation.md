# 官方 BIDS 校验与新输入注册

新 EEGMMIDB 工作副本明确声明 BIDS 1.11.1，使用固定 `bids-validator-deno 3.0.1`、`deno 2.9.6` 及安装包内置 Schema 1.2.7。校验 JS 的 SHA256 固定为 `6fba22693b737742468963cfa79b677c178ee597ea5abc5d2394b2088b7c82cf`，运行回执另保存 Deno 二进制哈希。不会在线加载新 Schema，也不会继承 `BIDS_SCHEMA` 或服务凭据。

完整工作流需安装 `--extra eeg --extra inspection`。缺少固定依赖、校验崩溃或超时、输出不完整、文件集合不一致、输入变化，均保存回执并阻止注册输入。独立校验旧副本时同时记录其原声明版本与本次检查规范；不会改写历史版本、结果或文件。

命令固定使用 `--format json --max-rows -1`，不忽略警告、不裁剪文件、不提供改变问题等级的配置；包含 `.bidsignore` 或覆盖配置的输入会阻塞。校验进程没有网络权限，只能在本次回执目录写入。默认 180 秒期限、2 GiB 进程树 RSS、单个输出 128 MiB 上限；超限结果不能视为完整。Windows Job/进程组控制负责取消和进程树回收。

原始官方问题列表原样保存。零错误且只缺少推荐元数据时，状态为 `passed_with_warnings`：按 code/field 保存每组出现次数及保留理由，明确缺项不能被编造，也不能作为依赖这些元数据的方法已适用的证明。其他没有固定保留理由的警告为 `review_required`，阻止注册。错误仍为错误，不通过改级或忽略绕过。出现次数是官方逐文件问题数，不等于独立缺失字段数。

每次运行的独立 UUID 目录位于 `collection/official-validator/`，含标准输出、错误日志、完整 `result.json` 和最后写入的 `receipt.json`。回执保存全体输入文件哈希、版本、命令、完整性及资源记录；`standardization.json` 绑定回执路径和哈希，注册输入的验证证据继续绑定该回执。停止后的回执可通过工作流产物列表下载。

官方标准校验与已有信号逐点往返、物理单位、通道/采样点/采样率、全部事件和映射检查共同完成。标准检查通过不证明实验语义正确、模板坐标为个体实测，或信号具有科学质量。新的注册发生在两类检查完成之后。

专项验证已覆盖真实校验器对第 1003 行错列的检出；作者版本的标准错误退出码为 16，与程序崩溃码 1 分开。第一次探索误用未带 v 的版本标签，第二次尝试不存在的 Schema 地址，两次都未产生成功结果；随后使用固定安装包内置规范，离线完整检查成功。首个长表试验发现退出码应为 16，修正解释器并在真实长表回归确认；失败证据保留。

参考：[官方命令行](https://bids-validator.readthedocs.io/en/stable/user_guide/command-line.html)、[作者仓库与配置说明](https://github.com/bids-standard/bids-validator)、[EEG 规范](https://bids-specification.readthedocs.io/en/stable/modality-specific-files/electroencephalography.html)。本实现以固定安装包字节为验收依据，不能以可变化的 stable 页面替代版本锁定。

全量真实验收：109 人、1526 记录、11013 文件，39569 源/标准事件、4918 训练试次，0 错误、70743 个缺失推荐字段警告；没有新增排除。总耗时 403.406 秒，原始数据和冻结代码不变。最终 29 项后端专项通过（54.84 秒）；另 27 项产物/进程/排除证据检查通过，包含重叠覆盖。见 [全量审计](sources/remaining-modifications-20260912/bids-fresh-2-audit.json) 与 [官方回执及所有文件哈希](sources/remaining-modifications-20260912/bids-fresh-2-official-receipt.json)。24 MB 原始官方问题列表保存在回执定位的本地 result.json，其 SHA256 在回执中；本次通过不等于所有研究问题已解决。
