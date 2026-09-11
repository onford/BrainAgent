# English-source localization / 英文基准双语维护

English is the source language for BrainAgent's interface. The default is `en`;
users can switch to Simplified Chinese (`zh`) in each page header. The choice is
stored as `brainagent.locale`. If browser storage is unavailable, switching still
works for the current page. The document language and date/number locale follow
the selection.

## Message ownership

- `frontend/src/i18n/en.ts` contains the source messages. Each English message is
  also its typed key. `frontend/src/i18n/zh.ts` supplies one Chinese translation
  for every key.
- Components call `t('Signal quality')`, or pass values into a complete sentence,
  such as `t('Open {0} →', { 0: title })`. Do not translate sentence fragments
  around interpolated values: English and Chinese may require different orders.
- Static label tables use getters so reading a label tracks the active locale.
  Derived data can use Vue `computed`. Do not capture translated labels once at
  module load, remount the application on a language change, or scan and replace
  arbitrary DOM text.
- Keep route values, status codes, operator IDs, metric IDs, units, filenames,
  protocol versions, and numerical records unchanged. Use stable IDs to select
  maintained labels; unknown extensions retain their supplied names.
- Historical reports, agent explanations, conversations, source excerpts, error
  records, and exported arrays remain in their original language and form. The
  interface language does not request a new model response, rerun an experiment,
  or silently translate evidence. A bilingual interface does not imply that old
  reports have English originals.
- The offline exporter bundles both catalogs. It uses the same switcher and
  preserves embedded report text and hashes. Its verification checks English
  startup and Chinese switching with no network requests.

## Terminology

Prefer the established English term and retain the abbreviation in both
languages. Translation must preserve the measurement's definition and scope.

| English source term | 中文 | Usage |
| --- | --- | --- |
| Power spectral density (PSD) | 功率谱密度 | Distinguish density from integrated band power; preserve the recorded units. |
| Balanced accuracy (BA) | 平衡准确率 | Class-wise recall averaged equally. Subject-macro BA adds a separate, equal-subject aggregation. |
| Epoch | 数据分段 | A signal segment; use *trial* for the experimental trial identity, not as a universal synonym. |
| Sampling frequency | 采样率 | Preserve Hz and the actual sampling grid. |
| Re-referencing | 重参考 | Changing the reference is distinct from rescaling or alignment. |
| Common spatial patterns (CSP) | 共空间模式 | Keep CSP-LDA as the recorded learner/benchmark identity. |
| Shrinkage LDA | 收缩线性判别分析 | Preserve the shrinkage qualification. |
| Euclidean alignment (EA) | 欧氏对齐 | The adaptation protocol determines which unlabeled data can be used. |
| ERD/ERS | 事件相关去同步化／同步化 | Preserve frequency band, baseline, sign convention, and applicable task. |
| Subject standard deviation | 被试标准差 | Describes between-subject variability. |
| Seed standard deviation | 种子标准差 | Describes training randomness; not interchangeable with subject SD. |
| Development evaluation | 开发评估 | Used in candidate selection; not an independent generalization test. |
| Offline transductive adaptation | 离线转导适配 | May use the target batch without labels; not a zero-target-information protocol. |
| Not applicable / not computable / missing | 不适用／无法计算／缺失 | Keep these states distinct; none means a zero measurement. |

Terminology references: [MNE filtering and resampling](https://mne.tools/stable/auto_tutorials/preprocessing/30_filtering_resampling.html)
for signal-processing names, and [scikit-learn balanced accuracy](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.balanced_accuracy_score.html)
for the BA definition. The project's evaluation protocol remains authoritative
for subject and seed aggregation.

## Updating and checking

1. Write or revise the English message first, then update its Chinese equivalent
   and all call sites in the same commit. Remove the obsolete key when unused.
2. Keep placeholder names/counts identical. Pass numbers and recorded identifiers
   as values; translations must not alter them. The catalog test checks coverage
   and placeholders, and TypeScript checks message keys.
3. Check both languages in context, especially long English labels, mobile
   navigation, accessible labels, and report controls. Preserve selections,
   input drafts, pagination, and reading position when switching.
4. Run the affected frontend tests and build. If report components or export
   integration change, verify the standalone export too. Commit and push the
   completed version without unrelated working-tree changes.

现行约定：英文是界面文案和术语的基准，中文逐项对应维护。新增或改写文案时，两种语言在同一提交中更新；缩写、单位、指标含义与协议语义保持一致。语言切换只影响应用界面，历史报告、对话、决策解释和实验记录保留原文。需要翻译这些内容时，应另行保存有来源标识的译文，不能覆盖原始证据。
