<script setup lang="ts">
import { reactive } from 'vue'
import { t } from '../../i18n'

export type WorkflowBudgets = {
  model_budget_seconds: number
  method_research_budget: { max_seconds: number; max_recovery_actions: number }
  search_budget: { max_candidates: number; max_seconds: number; max_memory_mb: number | null; max_disk_mb: number | null; [key: string]: number | null }
}
const props = defineProps<{ defaults: WorkflowBudgets }>()
const values = reactive({
  candidates: props.defaults.search_budget.max_candidates,
  searchHours: props.defaults.search_budget.max_seconds / 3600,
  modelHours: props.defaults.model_budget_seconds / 3600,
  methodMinutes: props.defaults.method_research_budget.max_seconds / 60,
  memory: props.defaults.search_budget.max_memory_mb ?? '' as number | string,
  disk: props.defaults.search_budget.max_disk_mb ?? '' as number | string,
})
function request(): WorkflowBudgets {
  const optional = (value: number | string) => value === '' ? null : Number(value)
  const memory = optional(values.memory), disk = optional(values.disk)
  if (!Number.isInteger(values.candidates) || values.candidates < 1 || values.candidates > 256 ||
    !Number.isFinite(values.searchHours) || values.searchHours <= 0 ||
    !Number.isFinite(values.modelHours) || Math.round(values.modelHours * 3600) < 1 || values.modelHours > 168 ||
    !Number.isFinite(values.methodMinutes) || values.methodMinutes <= 0 || values.methodMinutes > 1440 ||
    [memory, disk].some(value => value !== null && (!Number.isInteger(value) || value < 64))) {
    throw new Error(t('Enter valid budgets before starting.'))
  }
  return {
    model_budget_seconds: Math.round(values.modelHours * 3600),
    method_research_budget: { ...props.defaults.method_research_budget, max_seconds: values.methodMinutes * 60 },
    search_budget: { ...props.defaults.search_budget, max_candidates: values.candidates,
      max_seconds: values.searchHours * 3600, max_memory_mb: memory, max_disk_mb: disk },
  }
}
defineExpose({ request })
</script>

<template>
  <fieldset class="workflow-budgets">
    <legend>{{ t('Run budgets') }}</legend>
    <p>{{ t('These limits are saved with the run. Retrying does not reset them.') }}</p>
    <div class="budget-grid">
      <label>{{ t('Maximum candidates') }}<input v-model.number="values.candidates" type="number" min="1" max="256" step="1" required /></label>
      <label>{{ t('Search time limit (hours)') }}<input v-model.number="values.searchHours" type="number" min="0.0002777778" step="any" required /></label>
      <label>{{ t('Model deadline (hours)') }}<input v-model.number="values.modelHours" type="number" min="0.0002777778" max="168" step="any" required /></label>
      <label>{{ t('Method research time (minutes)') }}<input v-model.number="values.methodMinutes" type="number" min="0.000001" max="1440" step="any" required /></label>
      <label>{{ t('Memory limit (MiB)') }}<input v-model.number="values.memory" type="number" min="64" step="1" :placeholder="t('Automatic')" /></label>
      <label>{{ t('Disk limit (MiB)') }}<input v-model.number="values.disk" type="number" min="64" step="1" :placeholder="t('Automatic')" /></label>
    </div>
    <p>{{ t('The model deadline starts when the workflow is created and includes research, numerical execution and reporting.') }}</p>
  </fieldset>
</template>

<style scoped>
.workflow-budgets{border:1px solid #dce5de;border-radius:8px;padding:12px;margin:0 0 20px;min-width:0}
legend{font-size:13px;color:#365c43;padding:0 5px}.workflow-budgets p{font-size:12px;line-height:1.5;color:#687f70;margin:6px 0}
.budget-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.budget-grid label{display:block;margin:8px 0 0;font-size:12px;min-width:0}.budget-grid input{display:block;width:100%;padding:10px;margin-top:6px;border:1px solid #d4e0d7;border-radius:7px;font:inherit;box-sizing:border-box;min-width:0}
@media(max-width:400px){.budget-grid{grid-template-columns:1fr}}
</style>
