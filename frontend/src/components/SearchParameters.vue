<script setup lang="ts">
import { computed } from 'vue'
const props = defineProps<{ protocol: any; recipe?: any; panel?: any }>()
const operators = computed(() => props.protocol?.space?.operators ?? [])
const definition = (id: string) => Array.isArray(operators.value) ? operators.value.find((o: any) => o.id === id) : operators.value[id]
const training = computed(() => props.protocol?.utility_protocol?.eegnet?.training ?? props.protocol?.utility_execution?.eegnet_training)
const format = (value: unknown) => value == null ? '未记录' : typeof value === 'object' ? JSON.stringify(value) : String(value)
function domain(value: any) { return !value ? '固定或未记录' : value.kind === 'choice' ? format(value.values ?? value.choices) : `${value.minimum ?? '—'} ～ ${value.maximum ?? '—'} (${value.kind})` }
</script>
<template>
  <details class="parameters"><summary>本次运行的处理与训练参数</summary>
    <p>以下读取冻结协议和候选配方。展示不会修改历史运行；文献建议与工程默认值在解读知识库中单独说明。</p>
    <div class="scroll"><table><thead><tr><th>顺序 / 算子</th><th>配方参数</th><th>冻结允许域</th><th>拟合信息权限</th></tr></thead><tbody><tr v-for="(node, index) in recipe?.nodes ?? []" :key="node.id"><td>{{ Number(index)+1 }} · {{ definition(node.operator)?.title || node.operator }}</td><td><dl v-if="Object.keys(node.parameters || {}).length"><template v-for="(v, k) in node.parameters" :key="k"><dt>{{ k }}</dt><dd>{{ format(v) }}</dd></template></dl><span v-else>无可编辑参数；绑定值见输出网格</span></td><td><dl v-for="(v, k) in definition(node.operator)?.domains ?? {}" :key="k"><dt>{{ k }}</dt><dd>{{ domain(v) }} · {{ (v as any).unit }}<br />来源：{{ (v as any).origin }} · {{ (v as any).rationale }}<br />依据 ID：{{ format((v as any).evidence_ids) }}</dd></dl></td><td>{{ definition(node.operator)?.fit_scope || '未记录' }}</td></tr></tbody></table></div>
    <p v-if="!recipe?.nodes?.length">此运行没有保存算子配方；不使用当前默认参数填补。</p>
    <dl><dt>输出网格 / 任务窗</dt><dd>{{ format(panel?.output_contract) }}</dd><dt>无标签适配</dt><dd>{{ format(recipe?.adaptation) }}</dd><dt>选择规则</dt><dd>{{ format(protocol?.metric) }}</dd><dt>主模型 / 种子</dt><dd>{{ format(protocol?.utility_protocol?.primary_suite) }} / {{ format(protocol?.utility_protocol?.seeds ?? protocol?.utility_protocol?.eegnet?.seeds ?? protocol?.assessment?.seeds) }}</dd><dt>EEGNet 训练配置</dt><dd>{{ format(training) }}</dd><dt>模型进程上限</dt><dd>{{ format(protocol?.utility_execution?.max_workers) }}</dd><dt>拟合 / 早停规则</dt><dd>{{ format(protocol?.utility_protocol?.eegnet?.validation) }} · {{ format(protocol?.utility_protocol?.eegnet?.selection) }}</dd></dl>
    <details><summary>完整冻结参数（含固定绑定和 CSP）</summary><pre>{{ JSON.stringify({ utility: protocol?.utility_protocol, execution: protocol?.utility_execution, recipe, bindings: (recipe?.nodes ?? []).map((n: any) => ({ operator: n.operator, bindings: definition(n.operator)?.bindings })) }, null, 2) }}</pre></details>
  </details>
</template>
<style scoped>
.parameters{border:1px solid #dce6de;border-radius:9px;padding:14px 18px;margin:18px 0;font-size:12px;line-height:1.8}summary{font-size:13px;cursor:pointer;color:#376649}p{color:#687b6c}.scroll{overflow:auto}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:9px;border-bottom:1px solid #e7eee8;vertical-align:top}dl{display:grid;grid-template-columns:minmax(100px,150px) 1fr;gap:5px}dd{margin:0;overflow-wrap:anywhere}dt{color:#58745e}pre{max-height:300px;overflow:auto;white-space:pre-wrap}
</style>
