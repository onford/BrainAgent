<script setup lang="ts">
import { computed } from 'vue'
import { searchArtifactUrl } from '../api/searches'
const props = defineProps<{ searchId: string; protocol: Record<string, any>; diagnostics?: any[]; actions?: any[] }>()
const bundle = computed(() => props.protocol.neural_priors)
const sources = computed(() => Object.fromEntries((bundle.value?.sources ?? []).map((s: any) => [s.id, s])))
const citations = computed(() => (props.actions ?? []).filter(a => a.result?.prior_evidence?.status === 'cited_by_agent'))
const stateName = (s: string) => ({ true: '成立', false: '不成立', unknown: '未知' }[s] ?? s)
const sourceUrl = (id: string) => /^https:\/\//.test(sources.value[id]?.url ?? '') ? sources.value[id].url : undefined
const ruleTitle = (r: any) => ({ 'eog-missing': '至少一条记录缺少真实 EOG', 'iclabel-domain': '原始带宽不足以覆盖 1–100 Hz' }[r.id as string] ?? r.title)
const reasonName = (s: string) => ({ condition_satisfied: '观测满足当前条件', condition_not_satisfied: '观测未满足当前条件', no_available_members: '汇总中没有可用测量，请查看原始回执的缺失原因', missing_or_partial_observation: '测量缺失或仅部分可用', nonfinite_observation: '测量不是有限数值', acquisition_filter_history_incomplete_for_residual_proxy: '采集滤波历史不完整，残余污染代理不满足解释条件' }[s] ?? s)
const comparisonName = (s: string) => ({ gt: '大于', lt: '小于', eq: '等于', present: '存在有效观测' }[s] ?? s)
const originName = (s: string) => ({ engineering_screen: '工程筛查值，未经生理阈值验证', metadata: '冻结的采集元数据', descriptive: '描述性观测，无合格方向' }[s] ?? s)
const outcomeName = (s: string) => ({ condition_met: '条件成立', condition_not_met: '条件不成立', unavailable: '测量不可用' }[s] ?? s)
const actionName = (s: string) => ({ propose_candidate: '提出候选', request_evidence: '补充证据', request_diagnostic: '请求诊断', finish: '结束搜索' }[s] ?? s)
const responses = (id: string) => (props.actions ?? []).filter(a => a.status === 'completed' && a.action === 'model_decision' && a.result?.diagnostic_response?.diagnostic_id === id)
const temporalName = (s: string) => ({ normalized_change: '未对齐变化 NRMSE', gain: '相对增益', zero_lag_correlation: '零时移相关', lag_ms: '波形相关峰偏移', energy_centroid_shift_ms: '能量时间重心变化' }[s] ?? s)
const numericValue = (v: unknown) => typeof v === 'number' && Number.isFinite(v) ? v.toPrecision(5) : '不可用'
</script>

<template>
  <section class="neural-evidence">
    <h3>神经先验与实测依据</h3>
    <p v-if="!bundle">此运行未冻结神经先验包；不能据此声称 agent 使用了神经先验。</p>
    <template v-else>
      <p>先验用于提出可检验假设。筛查阈值不代表生理诊断标准，也不要求每个人出现典型 μ / β 活动。</p>
      <p>目录 {{ bundle.capabilities.catalog_units }} 个单元；已启用 {{ bundle.capabilities.enabled_units }} 个单元、{{ bundle.capabilities.enabled_operations }} 项操作；本次搜索支持 {{ bundle.capabilities.search_operators }} 个算子。</p>
      <a :href="searchArtifactUrl(searchId, { name: 'neural-priors.json' })" target="_blank" rel="noopener">查看冻结规则、任务条件、来源与调研缺口</a>
      <p v-if="!diagnostics?.length">尚无已执行诊断；规则存在不等于已被使用。</p>
      <p v-else>已执行 {{ diagnostics.length }} 项诊断；{{ citations.length }} 个决策记录了先验引用。引用记录本身不证明解释正确。</p>
      <article v-for="d in diagnostics" :key="d.id">
        <h4>{{ d.question }}</h4>
        <p>{{ d.candidate_id }} · {{ d.stage }} · {{ d.status }}</p>
        <div v-if="d.decision_effect" class="diagnostic-effect">
          <p>待验证假设：{{ d.decision_effect.experiment.hypothesis }}</p>
          <p>竞争解释：{{ d.decision_effect.experiment.competing_explanation }}</p>
          <p>实测条件：{{ outcomeName(d.decision_effect.outcome) }}；观测值 {{ d.decision_effect.value ?? '不可用' }}</p>
          <p>阈值依据：{{ d.decision_effect.experiment.threshold_rationale }}</p>
          <p>预登记下一步：{{ actionName(d.decision_effect.selected_branch.next_action) }} · {{ d.decision_effect.selected_branch.reason }}</p>
          <p>数值条件成立不代表机制已被证明。</p>
          <p v-if="!responses(d.id).length">尚未记录后续决定。</p>
          <p v-for="a in responses(d.id)" :key="a.index">实际决定：{{ actionName(a.result.decision.action) }} · {{ a.result.diagnostic_response.disposition === 'revise' ? '修订计划' : '遵循分支' }} · {{ a.result.diagnostic_response.reason }}</p>
        </div>
        <a v-if="d.artifact" :href="searchArtifactUrl(searchId, { name: d.artifact.path })" target="_blank" rel="noopener">完整诊断与测量定位</a>
        <div v-if="d.common_view_change" class="temporal-change">
          <h5>共同视图的波形与时间变化</h5>
          <p>保留原始幅度和时间位置；相关峰偏移不代表生理潜伏期。周期歧义、边界峰和缺测保留为不可用。</p>
          <table><thead><tr><th>测量</th><th>数值</th><th>单位</th><th>完整记录</th></tr></thead>
            <tbody><tr v-for="(m, name) in d.common_view_change.summary" :key="name"><td>{{ temporalName(String(name)) }}</td><td>{{ numericValue(m.value) }}</td><td>{{ m.unit }}</td><td>{{ m.available_records }} / {{ m.expected_records }}</td></tr></tbody>
          </table>
          <p v-for="r in d.common_view_change.records" :key="r.record_id">{{ r.record_id }}：{{ r.status === 'evaluated' ? `已测 ${r.expected_trial_channel_pairs} 个试次/通道对；${r.ambiguous_lag_pairs} 个偏移不可辨识` : '缺少已验证的共同视图，无法比较' }}</p>
          <p>这些变化不能分离纯伪迹，也不能证明神经信息无损。</p>
        </div>
        <details v-for="r in d.prior_evaluation?.rules" :key="r.id">
          <summary>{{ ruleTitle(r) }}：{{ stateName(r.condition_state) }}</summary>
          <p>观测：{{ r.observed?.value ?? '缺失' }} {{ r.observed?.unit }}；{{ reasonName(r.reason) }}</p>
          <p>条件：{{ comparisonName(r.comparison) }} {{ r.threshold ?? '' }}；{{ originName(r.threshold_origin) }}</p>
          <p v-if="r.condition_state === 'unknown'">证据不足，不能据此认定无污染或筛查条件已成立。</p>
          <p v-for="(count, cause) in r.observed?.missing_detail?.record_reason_counts" :key="cause">逐记录原因：{{ reasonName(String(cause)) }}（{{ count }} 条）</p>
          <p v-if="r.observed?.reference?.path"><a :href="searchArtifactUrl(searchId, { name: r.observed.reference.path })" target="_blank" rel="noopener">查看测量原始回执</a> · {{ r.observed.reference.json_pointer }}</p>
          <p>下一步：{{ r.implication }}</p><p>竞争解释：{{ r.alternative }}</p><p>保护条件：{{ r.protection }}</p>
          <p v-for="id in r.source_ids" :key="id"><a v-if="sourceUrl(id)" :href="sourceUrl(id)" target="_blank" rel="noopener">{{ sources[id]?.title ?? id }}</a><span v-else>{{ sources[id]?.title ?? id }}</span><span v-if="sources[id]?.locator"> · {{ sources[id].locator }}</span></p>
        </details>
        <details v-if="d.metrics"><summary>配对差异与不可比原因（候选 − 参考）</summary><pre>{{ JSON.stringify(d.metrics, null, 2) }}</pre></details>
      </article>
      <details v-if="citations.length"><summary>决策使用了哪些证据</summary><pre v-for="a in citations" :key="a.index">{{ JSON.stringify(a.result.prior_evidence, null, 2) }}</pre></details>
    </template>
  </section>
</template>

<style scoped>
.neural-evidence{padding:16px;border:1px solid #bdd1c7;border-radius:12px;background:#f7faf8;color:#203b32}.neural-evidence h3{margin-top:0}.neural-evidence p{line-height:1.6}.neural-evidence article{margin-top:16px;border-top:1px solid #ccd9d1;padding-top:8px}.neural-evidence details{margin:8px 0}.neural-evidence summary{cursor:pointer}.neural-evidence pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:320px;overflow:auto}
</style>
