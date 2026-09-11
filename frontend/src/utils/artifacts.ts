import { t } from '../i18n'
export type WorkflowArtifact = { name: string; bytes?: number | null; sha256: string | null; url?: string; description?: string }
export type ArtifactFamily = {
  key: string
  label: string
  files: WorkflowArtifact[]
  bytes: number | null
  description: string
}

const descriptions: Record<string, string> = {
  get 'workflow.json'() { return t('Run status, execution logs, and artifact index') },
  get 'training-data.zip'() { return t('Training-ready data and accompanying instructions') },
  get 'process/index.json'() { return t('Module status and structured record index') },
  get 'process/schema.json'() { return t('Record fields, types, and structural constraints') },
  get 'process/formats.json'() { return t('File formats, array types, and template fingerprints') },
  get 'survey/source-inventory.tsv'() { return t('Local source file paths and sizes') },
  get 'survey/survey.json'() { return t('Dataset information, per-record details, and research statistics') },
  get 'survey/local-inspection.json'() { return t('Per-record observations, shared configuration, and inspection coverage') },
  get 'survey/local-events.tsv'() { return t('Original event labels, onset and duration in seconds, and sample positions') },
  get 'survey/directory-tree.txt'() { return t('Local data directory and file hierarchy') },
  get 'survey/verification.json'() { return t('Item-by-item comparison of local data, official repository, and official paper') },
  get 'survey/literature.json'() { return t('Selection and purpose of papers and repositories for analysis, dataset discussion, and preprocessing') },
  get 'survey/reports/dataset-basic.html'() { return t('Dataset name, version, license, source, and task scope') },
  get 'survey/reports/data-information.html'() { return t('Evidence from cross-checking local files, official repository, and official paper') },
  get 'survey/reports/statistics.html'() { return t('Subject, record, duration, sampling frequency, channel, and event statistics') },
  get 'survey/reports/literature-usage.html'() { return t('Analysis and algorithm studies using this dataset') },
  get 'survey/reports/literature-discussion.html'() { return t('Studies of dataset characteristics, issues, and exclusions for ingestion checks') },
  get 'survey/reports/literature-preprocessing.html'() { return t('Preprocessing papers and repositories for comparable data') },
  get 'survey/triggers.tsv'() { return t('Original event markers and task meanings') },
  get 'collection/collection.json'() { return t('Ingestion results, retention statistics, and adapter notes') },
  get 'collection/input.json'() { return t('Standardized input snapshot for preprocessing') },
  get 'collection/pre-screen.json'() { return t('Dataset size before ingestion screening') },
  get 'collection/post-screen.json'() { return t('Retained data after ingestion screening') },
  get 'collection/delta.tsv'() { return t('Screening changes, reasons, and unknown items') },
  get 'collection/audit.json'() { return t('Fifteen ingestion checks, processing rules, and code version') },
  get 'collection/literature-exclusions.json'() { return t('Literature exclusions matched to local identifiers and their handling') },
  get 'collection/source-integrity.json'() { return t('Selected source file hashes and before/after integrity checks') },
  get 'collection/standardization.json'() { return t('Standardization scope, event retention, and validation level') },
  get 'collection/channel-mapping.tsv'() { return t('Original channel names and order mapped to standard channels') },
  get 'collection/event-mapping.tsv'() { return t('Original events mapped to standard events and training selection') },
  get 'collection/mapping.tsv'() { return t('Source files mapped to standardized copies') },
  get 'collection/anomalies.tsv'() { return t('Ingestion checks, issues, and handling records') },
  get 'collection/exclusions.tsv'() { return t('Excluded records and reasons') },
  get 'preprocessing/plan.json'() { return t('Candidate methods, parameters, and pending records') },
  get 'preprocessing/result.json'() { return t('Numerical execution results and artifact list') },
  get 'preprocessing/summary.json'() { return t('Candidate completion, event counts, and output shapes') },
  get 'evaluation/selection.json'() { return t('Selected method and recorded selection rationale') },
  get 'report/output.json'() { return t('Report file locations and formats') },
  get 'report/report.json'() { return t('Report template data extracted from process records') },
  get 'report/report.html'() { return t('Readable data processing report') },
  get 'delivery/output.json'() { return t('Data delivery completion record') },
  get 'delivery/manifest.json'() { return t('Package files, checksums, and training group statistics') },
  get 'delivery/X.npy'() { return t('Training signals: trials × channels × samples') },
  get 'delivery/y.npy'() { return t('Class ID for each trial') },
  get 'delivery/subjects.npy'() { return t('Subject ID for each trial') },
  get 'delivery/split.npy'() { return t('Training, validation, or test assignment for each trial') },
  get 'delivery/labels.json'() { return t('Class IDs mapped to left/right hand tasks') },
  get 'delivery/channels.json'() { return t('Channel order, sampling frequency, units, and time window') },
  get 'delivery/trial-index.tsv'() { return t('Training rows mapped to source records and events') },
  get 'delivery/method.json'() { return t('Selected preprocessing method and parameter definitions') },
  get 'delivery/selection.json'() { return t('Delivered method and saved selection record') },
  get 'delivery/sources.json'() { return t('Data sources, citations, and source file checksums') },
  get 'delivery/report.html'() { return t('Processing report included with training data') },
  get 'delivery/README.md'() { return t('Instructions for reading and using the training package') },
  get 'delivery/train_example.py'() { return t('Example fitting a model using training data only') },
}

const bidsDescriptions: Record<string, string> = {
  get 'eeg.eeg'() { return t('Continuous EEG in the standardized copy') },
  get 'eeg.vhdr'() { return t('Signal file references, channels, and sampling configuration') },
  get 'eeg.vmrk'() { return t('Event markers and signal positions') },
  get 'eeg.json'() { return t('Acquisition parameters, reference, and other metadata') },
  get 'channels.tsv'() { return t('Channel names, types, units, and status') },
  get 'electrodes.tsv'() { return t('Electrode coordinates') },
  get 'coordsystem.json'() { return t('Electrode coordinate system and units') },
  get 'scans.tsv'() { return t('Acquisition file index for this subject') },
  get 'events.tsv'() { return t('Event onset, duration, and task labels') },
  get 'events.json'() { return t('Event table columns and label definitions') },
  get 'participants.tsv'() { return t('Participant information in the standardized copy') },
  get 'participants.json'() { return t('Participant table field definitions') },
  get 'dataset_description.json'() { return t('BIDS dataset name, version, and description') },
  get 'README'() { return t('Standardized copy notes and citations') },
}

export function artifactDescription(name: string): string {
  if (name.endsWith('/decisions.json')) return t('Model decisions, validation results, and revision history')
  const research: Record<string, string> = {
    get 'survey/research-plan.json'() { return t('Research questions, literature categories, and retrieval plan') },
    get 'survey/research.json'() { return t('Source-grounded findings, reading coverage, and information gaps') },
    get 'survey/sources.json'() { return t('Retrieved results, source text, links, and retrieval records') },
    get 'collection/review.json'() { return t('Model review of task, labels, and ingestion applicability') },
    get 'collection/research.json'() { return t('Additional facts and evidence resolving ingestion questions') },
    get 'collection/sources.json'() { return t('Additional sources read during ingestion review') },
    get 'preprocessing/design.json'() { return t('Candidate designs, step parameters, and literature or engineering rationale') },
    get 'preprocessing/research.json'() { return t('Additional design references and unresolved questions') },
    get 'preprocessing/sources.json'() { return t('Source text and retrieval records supporting method design') },
    get 'preprocessing/revisions.json'() { return t('Validation failures and revisions of non-executable methods') },
    get 'report/narrative.json'() { return t('Explanations extracted from process records for report templates') },
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
      get 'provenance.json'() { return t('Executed parameters, processing steps, and environment versions') },
      get 'events.json'() { return t('Original events mapped to output epochs and retention status') },
      get 'delta.json'() { return t('Signal statistics and event changes before and after processing') },
      get 'signal_V.npy'() { return t('Preprocessed signal array in volts') },
      get 'data-epo.fif'() { return t('MNE epochs and events') },
      get 'data-raw.fif'() { return t('MNE continuous signal') },
      get 'failure.json'() { return t('Failure reason and completed steps') },
      get 'artifacts.json'() { return t('Intermediate results and array references for this step') },
    }
    if (records[filename]) return records[filename]
    if (/^parameters_\d+\.npy$/.test(filename)) return t('Parameter arrays used by this step')
    if (/^artifacts_\d+\.npy$/.test(filename)) return t('Intermediate arrays generated by this step')
  }
  const extension = filename.split('.').at(-1)!
  return ({get json() { return t('Structured record') }, get tsv() { return t('Tabular record') }, get npy() { return t('Numerical array') }, get fif() { return t('MNE signal file') },
    get html() { return t('Readable report') }, get md() { return t('Instructions') }, get zip() { return t('Archive') }, get py() { return t('Python script') }} as Record<string, string>)[extension] ?? t('Run output file')
}

const fileLabels: Record<string, string> = {
  get 'eeg.eeg'() { return t('EEG signal (.eeg)') },
  get 'eeg.vhdr'() { return t('BrainVision header (.vhdr)') },
  get 'eeg.vmrk'() { return t('BrainVision event markers (.vmrk)') },
  get 'eeg.json'() { return t('EEG acquisition metadata (.json)') },
  get 'channels.tsv'() { return t('Channel table (.tsv)') },
  get 'electrodes.tsv'() { return t('Electrode positions (.tsv)') },
  get 'coordsystem.json'() { return t('Electrode coordinate system (.json)') },
  get 'scans.tsv'() { return t('Acquisition file index (.tsv)') },
  get 'events.tsv'() { return t('Event table (.tsv)') },
  get 'events.json'() { return t('Event record (events.json)') },
  get 'provenance.json'() { return t('Execution provenance (provenance.json)') },
  get 'delta.json'() { return t('Processing changes (delta.json)') },
  get 'signal_V.npy'() { return t('Signal array (signal_V.npy)') },
  get 'data-epo.fif'() { return t('Epoch data (.fif)') },
  get 'failure.json'() { return t('Failure record (failure.json)') },
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
      family = { key, label, files: [], bytes: 0, description: artifact.description || artifactDescription(artifact.name) }
      families.set(key, family)
    }
    family.files.push(artifact)
    family.bytes = family.bytes !== null && knownArtifactSize(artifact.bytes) ? family.bytes + artifact.bytes : null
  }
  // Keep overview files immediately accessible, before the repeated file groups.
  return [...families.values()].sort((a, b) =>
    Number(a.files.length > 1) - Number(b.files.length > 1) || a.key.localeCompare(b.key),
  )
}

export function knownArtifactSize(bytes: unknown): bytes is number {
  return typeof bytes === 'number' && Number.isFinite(bytes) && bytes >= 0
}

export function artifactSize(bytes: unknown): string {
  if (!knownArtifactSize(bytes)) return t('Size unknown')
  return bytes < 1024 ? `${bytes} B` : bytes < 1024**2 ? `${(bytes / 1024).toFixed(1)} KB` : `${(bytes / 1024**2).toFixed(1)} MB`
}
