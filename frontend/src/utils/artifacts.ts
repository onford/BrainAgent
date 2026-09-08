export type WorkflowArtifact = { name: string; bytes: number; sha256: string | null }
export type ArtifactFamily = {
  key: string
  label: string
  files: WorkflowArtifact[]
  bytes: number
  description: string
}

const descriptions: Record<string, string> = {
  'workflow.json': '运行状态、执行日志与产物索引',
  'training-data.zip': '可直接用于训练的数据与配套说明',
  'process/index.json': '各模块状态及结构化记录入口',
  'process/schema.json': '记录字段、类型与结构约束',
  'process/formats.json': '文件格式、数组类型与模板指纹',
  'survey/source-inventory.tsv': '本地原始文件路径与大小清单',
  'survey/survey.json': '数据集资料、逐记录信息与调研统计',
  'survey/local-inspection.json': '本地实际文件头、数组、通道和事件的观测依据',
  'survey/directory-tree.txt': '本地数据目录与文件层级',
  'survey/verification.json': '本地、官网仓库与官方论文的逐项对比及差异',
  'survey/literature.json': '分析与算法、数据集讨论、预处理的论文和仓库筛选及用途',
  'survey/triggers.tsv': '原始事件标记与任务含义对照',
  'collection/collection.json': '数据接入结果、保留统计与适配说明',
  'collection/input.json': '传给预处理模块的标准化输入快照',
  'collection/pre-screen.json': '接入筛选前的数据规模',
  'collection/post-screen.json': '接入筛选后的保留规模',
  'collection/delta.tsv': '筛选前后的统计变化',
  'collection/mapping.tsv': '原始文件与标准副本的对应关系',
  'collection/anomalies.tsv': '接入检查结果、问题与处理记录',
  'collection/exclusions.tsv': '被排除的记录及原因',
  'preprocessing/plan.json': '候选方法、参数与待处理记录',
  'preprocessing/result.json': '数值任务执行结果及产物清单',
  'preprocessing/summary.json': '各候选的完成情况、事件数与输出形状',
  'evaluation/selection.json': '可选候选、随机种子与选择结果',
  'report/output.json': '报告文件入口与格式',
  'report/report.json': '从过程记录中摘取的报告模板数据',
  'report/report.html': '可阅读的数据处理报告',
  'delivery/output.json': '数据交付完成回执',
  'delivery/manifest.json': '包内文件、校验值及训练分组统计',
  'delivery/X.npy': '训练信号：Trial × 通道 × 时间点',
  'delivery/y.npy': '每个 Trial 的类别编号',
  'delivery/subjects.npy': '每个 Trial 对应的被试编号',
  'delivery/split.npy': '每个 Trial 的训练、验证或测试分组',
  'delivery/labels.json': '类别编号与左右手任务对照',
  'delivery/channels.json': '通道顺序、采样率、单位与时间窗口',
  'delivery/trial-index.tsv': '训练数据行与原始记录、事件的对应关系',
  'delivery/method.json': '所选预处理方法及参数定义',
  'delivery/selection.json': '本次随机选择的候选与依据',
  'delivery/sources.json': '数据来源、引用与源文件校验值',
  'delivery/report.html': '随训练数据交付的处理报告',
  'delivery/README.md': '训练数据包的读取与使用说明',
  'delivery/train_example.py': '仅用训练组拟合模型的运行示例',
}

const bidsDescriptions: Record<string, string> = {
  'eeg.eeg': '标准副本中的连续 EEG 信号',
  'eeg.vhdr': '信号文件引用、通道及采样配置',
  'eeg.vmrk': '事件标记及其在信号中的位置',
  'eeg.json': '采集参数、参考方式等元数据',
  'channels.tsv': '通道名称、类型、单位与状态',
  'electrodes.tsv': '电极位置坐标',
  'coordsystem.json': '电极坐标的参考系与单位',
  'scans.tsv': '该被试的采集文件索引',
  'events.tsv': '事件起始时间、时长与任务标签',
  'events.json': '事件表各列及标签的含义',
  'participants.tsv': '标准副本中的被试信息表',
  'participants.json': '被试信息表的字段说明',
  'dataset_description.json': 'BIDS 数据集名称、版本与说明',
  'README': '标准副本说明及引用信息',
}

export function artifactDescription(name: string): string {
  if (name.endsWith('/decisions.json')) return '模型的决策输出、校验结果与修订记录'
  const research: Record<string, string> = {
    'survey/research-plan.json': '模型拆解的调研问题、文献分类与检索计划',
    'survey/research.json': '有原文依据的调研结论、论文阅读范围与待补信息',
    'survey/sources.json': '实际检索结果、来源正文、链接和获取记录',
    'collection/review.json': '模型对任务、标签和数据接入适用性的核对',
    'collection/research.json': '为解决接入疑问补充核对的事实与依据',
    'collection/sources.json': '接入核对阶段实际读取的补充来源',
    'preprocessing/design.json': '模型设计的候选方案、步骤参数及文献或工程依据',
    'preprocessing/research.json': '方案设计阶段补充的文献依据与待解决问题',
    'preprocessing/sources.json': '为方案补充获取的来源正文和检索记录',
    'preprocessing/revisions.json': '不可执行方案的校验原因与修订历史',
    'report/narrative.json': '从过程记录提炼、供报告模板使用的解释文字',
  }
  if (research[name]) return research[name]
  if (descriptions[name]) return descriptions[name]
  const filename = name.split('/').at(-1)!
  if (name.startsWith('collection/bids/')) {
    const suffix = filename.split('_').at(-1)!
    const description = bidsDescriptions[filename] ?? bidsDescriptions[suffix]
    if (description) return description
  }
  if (name.startsWith('preprocessing/runs/') || name.startsWith('delivery/provenance/')) {
    const records: Record<string, string> = {
      'provenance.json': '实际执行参数、处理步骤与环境版本',
      'events.json': '原始事件到输出 Epoch 的映射与保留情况',
      'delta.json': '处理前后的信号统计与事件变化',
      'signal_V.npy': '预处理后的信号数组，单位 V',
      'data-epo.fif': 'MNE 格式的分段信号与事件',
      'data-raw.fif': 'MNE 格式的连续信号',
      'failure.json': '失败原因与已完成步骤',
      'artifacts.json': '该处理步骤的中间结果与数组引用',
    }
    if (records[filename]) return records[filename]
    if (/^parameters_\d+\.npy$/.test(filename)) return '该处理步骤使用的参数数组'
    if (/^artifacts_\d+\.npy$/.test(filename)) return '该处理步骤生成的中间数组'
  }
  const extension = filename.split('.').at(-1)!
  return ({json: '结构化记录', tsv: '表格记录', npy: '数值数组', fif: 'MNE 信号文件',
    html: '可阅读的报告', md: '使用说明', zip: '打包文件', py: 'Python 脚本'} as Record<string, string>)[extension] ?? '运行产出文件'
}

const fileLabels: Record<string, string> = {
  'eeg.eeg': 'EEG 信号（.eeg）',
  'eeg.vhdr': 'BrainVision 文件头（.vhdr）',
  'eeg.vmrk': 'BrainVision 事件标记（.vmrk）',
  'eeg.json': 'EEG 采集信息（.json）',
  'channels.tsv': '通道表（.tsv）',
  'electrodes.tsv': '电极位置（.tsv）',
  'coordsystem.json': '电极坐标系（.json）',
  'scans.tsv': '采集文件索引（.tsv）',
  'events.tsv': '事件表（.tsv）',
  'events.json': '事件记录（events.json）',
  'provenance.json': '执行溯源（provenance.json）',
  'delta.json': '处理前后变化（delta.json）',
  'signal_V.npy': '信号数组（signal_V.npy）',
  'data-epo.fif': 'Epoch 数据（.fif）',
  'failure.json': '失败记录（failure.json）',
}

function familyOf(name: string): { key: string; label: string } {
  if (name.startsWith('collection/bids/')) {
    // Only record identity varies. Preserve task, space, suffix and extension.
    const key = name.replace(/(^|[/_])(sub|ses|run)-[a-zA-Z0-9]+(?=[/_.])/g, '$1$2-*')
    const suffix = name.split('/').at(-1)!.split('_').at(-1)!
    return { key, label: fileLabels[suffix] ?? suffix }
  }
  const worker = name.match(/^preprocessing\/runs\/[^/]+\/r\d+\/a\d+\/(.+)$/)
  const delivery = name.match(/^delivery\/provenance\/[^/]+\/(.+)$/)
  const tail = worker?.[1] ?? delivery?.[1]
  if (tail) {
    const filename = tail.split('/').at(-1)!
    const step = tail.includes('/') ? tail.slice(0, tail.lastIndexOf('/') + 1) : ''
    return {
      key: (worker ? 'preprocessing/runs/*/r*/a*/' : 'delivery/provenance/*/') + tail,
      label: step + (fileLabels[filename] ?? filename),
    }
  }
  return { key: name, label: name }
}

export function groupArtifactFiles(files: WorkflowArtifact[]): ArtifactFamily[] {
  const families = new Map<string, ArtifactFamily>()
  for (const artifact of files) {
    const { key, label } = familyOf(artifact.name)
    let family = families.get(key)
    if (!family) {
      family = { key, label, files: [], bytes: 0, description: artifactDescription(artifact.name) }
      families.set(key, family)
    }
    family.files.push(artifact)
    family.bytes += artifact.bytes
  }
  // Keep overview files immediately accessible, before the repeated file groups.
  return [...families.values()].sort((a, b) =>
    Number(a.files.length > 1) - Number(b.files.length > 1) || a.key.localeCompare(b.key),
  )
}
