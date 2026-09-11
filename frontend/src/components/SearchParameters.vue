<script setup lang="ts">
import { t } from '../i18n'
import { computed } from 'vue'
const props = defineProps<{ protocol: any; recipe?: any; panel?: any; expanded?: boolean }>()
const operators = computed(() => props.protocol?.space?.operators ?? [])
const definition = (id: string) => Array.isArray(operators.value) ? operators.value.find((o: any) => o.id === id) : operators.value[id]
const training = computed(() => props.protocol?.utility_protocol?.eegnet?.training ?? props.protocol?.utility_execution?.eegnet_training)
const format = (value: unknown) => value == null ? t('Not recorded') : typeof value === 'object' ? JSON.stringify(value) : String(value)
function domain(value: any) { return !value ? t('Fixed or not recorded') : value.kind === 'choice' ? format(value.values ?? value.choices) : `${value.minimum ?? '—'} ～ ${value.maximum ?? '—'} (${value.kind})` }
const origins: Record<string, string> = { get engineering() { return t('Engineering convention') }, get literature() { return t('Literature evidence') }, get mathematical() { return t('Mathematical constraint') }, get implementation() { return t('Implementation constraint') } }
const fitScopes: Record<string, string> = { get none() { return t('No fitting required') }, get source_train() { return t('Source training data only') }, get target_unlabelled() { return t('Unlabeled target data') } }
const trainingNames: Record<string, string> = { get max_epochs() { return t('Maximum epochs') }, get patience() { return t('Early-stopping patience') }, get batch_size() { return t('Batch size') }, get learning_rate() { return t('Learning rate') }, get validation_fraction() { return t('Validation fraction for early stopping') }, get split_seed() { return t('Split seed') } }
const grid = computed(() => props.panel?.output_contract)
</script>
<template>
  <details class="parameters" :open="expanded">
    <summary>{{ t('Run parameters') }}<span>{{ t('Processing order · Data scope · Training configuration') }}</span></summary>
    <p class="note">{{ t('Parameters used in this run. Allowed ranges define search bounds, not recommended values.') }}</p>
    <h4>{{ t('Processing order') }}</h4>
    <ol v-if="recipe?.nodes?.length" class="operators">
      <li v-for="(node, index) in recipe.nodes" :key="node.id">
        <span class="order">{{ Number(index)+1 }}</span>
        <div class="operator-body">
          <strong>{{ definition(node.operator)?.title || node.operator }}</strong>
          <small>{{ fitScopes[definition(node.operator)?.fit_scope] || definition(node.operator)?.fit_scope || t('Fitting data scope not recorded') }}</small>
          <dl v-if="Object.keys(node.parameters || {}).length"><template v-for="(v, k) in node.parameters" :key="k"><dt>{{ k }}</dt><dd>{{ format(v) }} {{ definition(node.operator)?.domains?.[k]?.unit }}</dd></template></dl>
          <p v-else class="note">{{ t('Fixed step. See the full protocol for its settings.') }}</p>
          <details v-if="Object.keys(definition(node.operator)?.domains ?? {}).length" class="domains">
            <summary>{{ t('Allowed ranges and rationale') }}</summary>
            <dl v-for="(v, k) in definition(node.operator)?.domains ?? {}" :key="k"><dt>{{ k }}</dt><dd>{{ domain(v) }} · {{ (v as any).unit }}<p>{{ origins[(v as any).origin] || (v as any).origin }} · {{ (v as any).rationale }}</p><small v-if="(v as any).evidence_ids?.length">{{ t('Evidence IDs: {0}', { 0: format((v as any).evidence_ids) }) }}</small></dd></dl>
          </details>
        </div>
      </li>
    </ol>
    <p v-else class="note">{{ t('No operator recipe was saved.') }}</p>
    <div class="parameter-columns">
      <section><h4>{{ t('Data and evaluation') }}</h4><dl>
        <dt>{{ t('Channels') }}</dt><dd>{{ grid?.channels?.length ?? t('Not recorded') }}</dd>
        <dt>{{ t('Output sampling frequency') }}</dt><dd>{{ format(grid?.sfreq) }}<template v-if="grid?.sfreq != null"> Hz</template></dd>
        <dt>{{ t('Task time window') }}</dt><dd>{{ format(grid?.tmin) }} ～ {{ format(grid?.tmax) }} s</dd>
        <dt>{{ t('Primary model') }}</dt><dd>{{ format(protocol?.utility_protocol?.primary_suite) }}</dd>
        <dt>{{ t('Training seeds') }}</dt><dd>{{ format(protocol?.utility_protocol?.seeds ?? protocol?.utility_protocol?.eegnet?.seeds ?? protocol?.assessment?.seeds) }}</dd>
        <dt>{{ t('Maximum concurrent models') }}</dt><dd>{{ format(protocol?.utility_execution?.max_workers) }}</dd>
      </dl></section>
      <section><h4>{{ t('EEGNet training configuration') }}</h4><dl v-if="training"><template v-for="(v, k) in training" :key="k"><dt>{{ trainingNames[String(k)] || k }}</dt><dd>{{ format(v) }}</dd></template></dl><p v-else class="note">{{ t('This protocol has no recorded EEGNet training configuration.') }}</p></section>
    </div>
    <details class="raw"><summary>{{ t('Full parameter record') }}</summary><pre>{{ JSON.stringify({ output_contract: grid, selection: protocol?.metric, utility: protocol?.utility_protocol, execution: protocol?.utility_execution, recipe, bindings: (recipe?.nodes ?? []).map((n: any) => ({ operator: n.operator, bindings: definition(n.operator)?.bindings })) }, null, 2) }}</pre></details>
  </details>
</template>
<style scoped>
.parameters { border: 1px solid #dce5e7; border-radius: 12px; padding: 18px 20px; margin: 24px 0 16px; background: #fff; color: #253e43; font-size: 13px; line-height: 1.8; }
summary { cursor: pointer; color: #176e65; }
.parameters > summary { font-size: 15px; font-weight: 600; color: #253e43; }
.parameters > summary span { font-size: 12px; font-weight: 400; color: #586f75; display: inline-block; margin-left: 12px; }
.note, small { color: #586f75; font-size: 12px; }
small { display: block; }
h4 { font-size: 13px; margin: 20px 0 12px; }
.operators { list-style: none; padding: 0; margin: 0; display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 12px; }
.operators > li { display: flex; align-items: flex-start; gap: 12px; padding: 14px; background: #f5f8f9; border: 1px solid #e4ebed; border-radius: 8px; }
.order { display: grid; place-items: center; width: 26px; height: 26px; flex: 0 0 auto; border-radius: 50%; color: #176e65; background: #e1efeb; font-size: 12px; }
.operator-body { min-width: 0; flex: 1; }
.parameter-columns { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 28px; }
dl { display: grid; grid-template-columns: minmax(90px, .8fr) minmax(0, 1fr); gap: 6px 16px; }
dt { color: #586f75; } dd { margin: 0; overflow-wrap: anywhere; font-variant-numeric: tabular-nums; }
.domains { font-size: 12px; margin-top: 10px; }
.domains p { margin: 5px 0; }
.raw { margin-top: 18px; padding-top: 14px; border-top: 1px solid #e4ebed; }
pre { max-height: 320px; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; padding: 14px; background: #f5f8f9; font-size: 12px; }
@media(max-width: 680px) { .operators, .parameter-columns { grid-template-columns: 1fr; } .parameters { padding: 14px; } }
</style>
