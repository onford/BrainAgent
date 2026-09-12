import { computed, defineComponent, provide, ref } from 'vue'
import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it } from 'vitest'
import AssessmentPlot from './AssessmentPlot.vue'
import AssessmentHeatmap from './AssessmentHeatmap.vue'
import FigureComparisonPanel from './FigureComparisonPanel.vue'
import { comparisonFigures, comparisonScope, MAX_COMPARISON_FIGURES, useFigureComparison, type SeriesFigure } from '../utils/figureComparison'
import { setLocale } from '../i18n'

const seedFigure = (candidate: string): SeriesFigure => ({ kind: 'series', title: 'Seeds', caption: 'Three seeds', comparisonKey: 'utility:ba:seeds', categorical: true, xLabel: 'Seed', yLabel: 'BA', xDomain: [.5, 3.5], yDomain: [0, 1], provenance: { candidate_id: candidate, assessment_path: 'assessment/a1', metric: 'ba' }, series: [{ id: 'eegnet', name: 'EEGNet', connect: false, points: [{ x: 1, label: 'seed 17', y: .6 }, { x: 2, label: 'seed 42', y: null }, { x: 3, label: 'seed 2026', y: .7 }] }] })
beforeEach(() => setLocale('en'))

describe('selected figure comparisons', () => {
  it('freezes data, survives candidate remounts and isolates search scopes', () => {
    const scope = ref('snapshot-test'), store = useFigureComparison(scope)
    store.clear()
    const figure = seedFigure('candidate-a')
    store.toggle(figure)
    figure.series[0]!.points[0]!.y = .99
    expect((store.entries.value[0]!.figure as SeriesFigure).series[0]!.points[0]!.y).toBe(.6)
    expect(useFigureComparison(ref('snapshot-test')).entries.value).toHaveLength(1)
    scope.value = 'another-search'
    expect(store.entries.value).toHaveLength(0)
    scope.value = 'snapshot-test'
    // Locale-only title changes do not create duplicate snapshots.
    store.toggle({ ...seedFigure('candidate-a'), title: '按种子对比' })
    expect(store.entries.value).toHaveLength(0)
    for (let i = 0; i <= MAX_COMPARISON_FIGURES; i++) store.toggle(seedFigure(`candidate-${i}`))
    expect(store.entries.value).toHaveLength(MAX_COMPARISON_FIGURES)
    store.remove(store.entries.value[0]!.identity)
    store.toggle(seedFigure('replacement'))
    expect(store.entries.value).toHaveLength(MAX_COMPARISON_FIGURES)
    store.clear()
  })

  it('aligns categorical identities across reordered and missing conditions without changing values', () => {
    const store = useFigureComparison(ref('category-test')); store.clear()
    const first = seedFigure('a'), second = seedFigure('b')
    second.series[0]!.points = [{ x: 1, label: 'seed 2026', y: .8 }, { x: 2, label: 'seed 17', y: .5 }, { x: 3, label: 'new seed', y: .9 }]
    store.toggle(first); store.toggle(second)
    const compared = comparisonFigures(store.entries.value) as SeriesFigure[]
    expect(compared[0]!.xDomain).toEqual(compared[1]!.xDomain)
    expect(compared[1]!.series[0]!.points.map(p => [p.label, p.x, p.y])).toEqual([['seed 2026', 3, .8], ['seed 17', 1, .5], ['new seed', 4, .9]])
    expect(compared[0]!.series[0]!.points[1]!.y).toBeNull()
    expect((store.entries.value[1]!.figure as SeriesFigure).series[0]!.points[0]!.x).toBe(1)
    store.clear()
  })

  it('selects a subset of heatmaps, shares color limits and keeps gaps and full matrices', async () => {
    const scope = ref('heatmap-test'), store = useFigureComparison(scope); store.clear()
    const Harness = defineComponent({ components: { AssessmentHeatmap, FigureComparisonPanel }, setup() { provide(comparisonScope, scope); return {} }, template: `<div><FigureComparisonPanel /><AssessmentHeatmap v-for="(ch, i) in ['C3', 'Cz', 'C4']" :key="ch" comparison-key="tfr" comparison-label="TFR" :title="ch" :rows="['8 Hz','10 Hz']" :columns="['0 s','1 s']" :values="[[i+1,null],[-i-2,1]]" unit="%" caption="Relative baseline" diverging full-matrix :provenance="{candidate_id:'a',record_id:'S001R04',stage:'processed_task',channel:ch}" /></div>` })
    const w = mount(Harness)
    const boxes = w.findAll('input[type=checkbox]')
    await boxes[0]!.setValue(true); await boxes[2]!.setValue(true)
    await w.find('.comparison-toolbar button').trigger('click')
    const cards = w.findAll('.comparison-card')
    expect(cards).toHaveLength(2)
    expect(cards[0]!.text()).toContain('C3'); expect(cards[1]!.text()).toContain('C4')
    const specs = cards.map(c => JSON.parse(c.find('metadata').text()))
    expect(specs.map(s => s.rendering.colorLimits)).toEqual([[-4, 4], [-4, 4]])
    expect(specs[0].values).toEqual([[1, null], [-2, 1]])
    expect(specs[1].values).toEqual([[3, null], [-4, 1]])
    expect(specs.every(s => s.rendering.full_matrix)).toBe(true)
    expect(w.findAll('input[type=checkbox]')).toHaveLength(3) // Comparison panels cannot select themselves.
    await cards[0]!.find('.comparison-source button').trigger('click')
    expect((boxes[0]!.element as HTMLInputElement).checked).toBe(false)
    await w.findAll('.comparison-toolbar button')[1]!.trigger('click')
    expect(w.findAll('.comparison-card')).toHaveLength(0)
    expect((boxes[2]!.element as HTMLInputElement).checked).toBe(false)
    w.unmount()
  })

  it('preserves selection across keyed candidate changes and groups different metrics', async () => {
    const scope = ref('candidate-test'), store = useFigureComparison(scope); store.clear()
    const candidate = ref('a'), metric = ref('ba')
    const Harness = defineComponent({ components: { AssessmentPlot, FigureComparisonPanel }, setup() { provide(comparisonScope, scope); return { candidate, figure: computed(() => ({ ...seedFigure(candidate.value), comparisonKey: `utility:${metric.value}:seeds`, yLabel: metric.value, provenance: {candidate_id: candidate.value, metric: metric.value} })) } }, template: '<div><FigureComparisonPanel /><AssessmentPlot :key="candidate" v-bind="figure" /></div>' })
    const w = mount(Harness)
    await w.find('input[type=checkbox]').setValue(true)
    candidate.value = 'b'; await w.vm.$nextTick()
    expect((w.find('input').element as HTMLInputElement).checked).toBe(false)
    await w.find('input').setValue(true)
    await w.find('.comparison-toolbar button').trigger('click')
    expect(w.findAll('.comparison-card')).toHaveLength(2)
    metric.value = 'auc'; await w.vm.$nextTick()
    await w.find('input').setValue(true)
    expect(w.findAll('.comparison-groups button')).toHaveLength(2)
    expect(w.findAll('.comparison-card')).toHaveLength(2)
    await w.findAll('.comparison-groups button')[1]!.trigger('click')
    expect(w.findAll('.comparison-card')).toHaveLength(1)
    expect(w.find('[role=status]').text()).toContain('another figure')
    w.unmount(); store.clear()
  })
})
