import { describe, expect, it } from 'vitest'
import { groupArtifactFiles } from './artifacts'

const artifacts = (names: string[]) => names.map(name => ({name, bytes: 1024, sha256: null}))

describe('artifact families', () => {
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
