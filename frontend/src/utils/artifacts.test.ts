import { describe, expect, it } from 'vitest'
import { artifactDescription, artifactSize, groupArtifactFiles } from './artifacts'

const artifacts = (names: string[]) => names.map(name => ({name, bytes: 1024, sha256: null}))

describe('artifact families', () => {
  it.each([null, undefined, NaN, Infinity, -1])('preserves unknown size %s without treating it as zero', bytes => {
    expect(artifactSize(bytes)).toBe('大小未知')
    const names = ['preprocessing/runs/job/r0000/a1/events.json', 'preprocessing/runs/job/r0001/a1/events.json']
    const files = names.map((name, index) => ({ name, bytes: index === 0 ? bytes : 1024, sha256: null }))
    expect(groupArtifactFiles(files)[0]!.bytes).toBeNull()
    expect(groupArtifactFiles([...files].reverse())[0]!.bytes).toBeNull()
  })

  it('preserves a real empty file and supplied family descriptions', () => {
    expect(artifactSize(0)).toBe('0 B')
    expect(artifactSize(1024)).toBe('1.0 KB')
    const [family] = groupArtifactFiles([{ name: 'preprocessing/search/receipt.json', bytes: 0, sha256: null, description: '保存的预测核验' }])
    expect(family?.bytes).toBe(0)
    expect(family?.description).toBe('保存的预测核验')
  })

  it('describes saved selection artifacts neutrally', () => {
    for (const name of ['evaluation/selection.json', 'delivery/selection.json']) {
      expect(artifactDescription(name)).toContain('保存的选择')
      expect(artifactDescription(name)).not.toContain('开发评估')
      expect(artifactDescription(name)).not.toContain('随机')
    }
  })

  it('groups BIDS identities without mixing tasks, spaces or file types', () => {
    const files = artifacts([
      'collection/bids/sub-001/eeg/sub-001_task-mi_run-04_eeg.eeg',
      'collection/bids/sub-001/eeg/sub-001_task-mi_run-08_eeg.eeg',
      'collection/bids/sub-002/eeg/sub-002_task-mi_run-04_eeg.eeg',
      'collection/bids/sub-001/eeg/sub-001_task-rest_run-04_eeg.eeg',
      'collection/bids/sub-001/eeg/sub-001_task-mi_run-04_eeg.vhdr',
      'collection/bids/sub-001/eeg/sub-001_space-CapTrak_electrodes.tsv',
      'collection/bids/sub-002/eeg/sub-002_space-MNI_electrodes.tsv',
      'collection/bids/participants.tsv',
    ])
    const groups = groupArtifactFiles(files)
    const combined = groups.filter(g => g.files.length > 1)
    expect(combined).toHaveLength(1)
    expect(combined[0]!.files).toEqual(files.slice(0, 3))
    expect(combined[0]!.bytes).toBe(3072)
    expect(groups.flatMap(g => g.files).map(f => f.name).sort()).toEqual(files.map(f => f.name).sort())
  })

  it('groups repeated execution and delivery records while preserving stage and parameter differences', () => {
    const files = artifacts([
      'preprocessing/runs/job/r0000/a1/filter/artifacts.json',
      'preprocessing/runs/job/r0001/a2/filter/artifacts.json',
      'preprocessing/runs/job/r0001/a2/epochs/artifacts.json',
      'preprocessing/runs/job/r0001/a2/epochs/parameters_1.npy',
      'preprocessing/runs/job/r0001/a2/epochs/parameters_2.npy',
      'delivery/provenance/S001R04/events.json',
      'delivery/provenance/S001R08/events.json',
      'delivery/manifest.json',
    ])
    const combined = groupArtifactFiles(files).filter(g => g.files.length > 1)
    expect(combined.map(g => g.files.map(f => f.name))).toEqual([
      files.slice(5, 7).map(f => f.name), files.slice(0, 2).map(f => f.name),
    ])
  })
})
