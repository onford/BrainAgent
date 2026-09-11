<script setup lang="ts">
import { computed } from 'vue'
const props = defineProps<{ protocol: any; recipe?: any; panel?: any; expanded?: boolean }>()
const operators = computed(() => props.protocol?.space?.operators ?? [])
const definition = (id: string) => Array.isArray(operators.value) ? operators.value.find((o: any) => o.id === id) : operators.value[id]
const training = computed(() => props.protocol?.utility_protocol?.eegnet?.training ?? props.protocol?.utility_execution?.eegnet_training)
const format = (value: unknown) => value == null ? '未记录' : typeof value === 'object' ? JSON.stringify(value) : String(value)
function domain(value: any) { return !value ? '固定或未记录' : value.kind === 'choice' ? format(value.values ?? value.choices) : `${value.minimum ?? '—'} ～ ${value.maximum ?? '—'} (${value.kind})` }
const origins: Record<string, string> = { engineering: '工程约定', literature: '文献依据', mathematical: '数学约束', implementation: '实现约束' }
const fitScopes: Record<string, string> = { none: '无需拟合', source_train: '仅源训练数据', target_unlabelled: '目标无标签数据' }
const trainingNames: Record<string, string> = { max_epochs: '训练轮数上限', patience: '早停耐心轮数', batch_size: '批大小', learning_rate: '学习率', validation_fraction: '早停验证比例', split_seed: '划分种子' }
const grid = computed(() => props.panel?.output_contract)
</script>
<template>
  <details class="parameters" :open="expanded">
    <summary>运行参数 <span>处理顺序 · 数据范围 · 训练配置</span></summary>
    <p class="note">以下为本次参数；允许范围是搜索边界，不是推荐值。</p>
    <h4>处理顺序</h4>
    <ol v-if="recipe?.nodes?.length" class="operators">
      <li v-for="(node, index) in recipe.nodes" :key="node.id">
        <span class="order">{{ Number(index)+1 }}</span>
        <div class="operator-body">
          <strong>{{ definition(node.operator)?.title || node.operator }}</strong>
          <small>{{ fitScopes[definition(node.operator)?.fit_scope] || definition(node.operator)?.fit_scope || '拟合数据范围未记录' }}</small>
          <dl v-if="Object.keys(node.parameters || {}).length"><template v-for="(v, k) in node.parameters" :key="k"><dt>{{ k }}</dt><dd>{{ format(v) }} {{ definition(node.operator)?.domains?.[k]?.unit }}</dd></template></dl>
          <p v-else class="note">固定步骤，具体设置见完整协议。</p>
          <details v-if="Object.keys(definition(node.operator)?.domains ?? {}).length" class="domains">
            <summary>允许范围与依据</summary>
            <dl v-for="(v, k) in definition(node.operator)?.domains ?? {}" :key="k"><dt>{{ k }}</dt><dd>{{ domain(v) }} · {{ (v as any).unit }}<p>{{ origins[(v as any).origin] || (v as any).origin }} · {{ (v as any).rationale }}</p><small v-if="(v as any).evidence_ids?.length">依据 ID：{{ format((v as any).evidence_ids) }}</small></dd></dl>
          </details>
        </div>
      </li>
    </ol>
    <p v-else class="note">未保存算子配方。</p>
    <div class="parameter-columns">
      <section><h4>数据与评价</h4><dl>
        <dt>通道数</dt><dd>{{ grid?.channels?.length ?? '未记录' }}</dd>
        <dt>输出采样率</dt><dd>{{ format(grid?.sfreq) }}<template v-if="grid?.sfreq != null"> Hz</template></dd>
        <dt>任务时间窗</dt><dd>{{ format(grid?.tmin) }} ～ {{ format(grid?.tmax) }} s</dd>
        <dt>主模型</dt><dd>{{ format(protocol?.utility_protocol?.primary_suite) }}</dd>
        <dt>训练种子</dt><dd>{{ format(protocol?.utility_protocol?.seeds ?? protocol?.utility_protocol?.eegnet?.seeds ?? protocol?.assessment?.seeds) }}</dd>
        <dt>模型并发上限</dt><dd>{{ format(protocol?.utility_execution?.max_workers) }}</dd>
      </dl></section>
      <section><h4>EEGNet 训练配置</h4><dl v-if="training"><template v-for="(v, k) in training" :key="k"><dt>{{ trainingNames[String(k)] || k }}</dt><dd>{{ format(v) }}</dd></template></dl><p v-else class="note">此协议未记录 EEGNet 训练配置。</p></section>
    </div>
    <details class="raw"><summary>完整参数记录</summary><pre>{{ JSON.stringify({ output_contract: grid, selection: protocol?.metric, utility: protocol?.utility_protocol, execution: protocol?.utility_execution, recipe, bindings: (recipe?.nodes ?? []).map((n: any) => ({ operator: n.operator, bindings: definition(n.operator)?.bindings })) }, null, 2) }}</pre></details>
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
