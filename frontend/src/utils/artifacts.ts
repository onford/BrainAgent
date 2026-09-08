export type WorkflowArtifact = { name: string; bytes: number; sha256: string | null }
export type ArtifactFamily = {
  key: string
  label: string
  files: WorkflowArtifact[]
  bytes: number
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
      family = { key, label, files: [], bytes: 0 }
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
