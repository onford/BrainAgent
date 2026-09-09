import { mount } from '@vue/test-utils'
import { expect, it } from 'vitest'
import ArtifactExplorer from './ArtifactExplorer.vue'

it('loads large families progressively and searches beyond loaded files', async () => {
  const artifacts = Array.from({length:109},(_,i)=>{
    const id = String(i+1).padStart(3,'0')
    return {name:`collection/bids/sub-${id}/eeg/sub-${id}_task-mi_run-04_eeg.eeg`,bytes:100,sha256:null}
  })
  const wrapper = mount(ArtifactExplorer,{props:{artifacts,workflowId:'run',fileUrl:(name:string)=>name}})
  expect(wrapper.findAll('a')).toHaveLength(0)
  const details = wrapper.get('details')
  ;(details.element as HTMLDetailsElement).open = true
  await details.trigger('toggle')
  expect(wrapper.findAll('a')).toHaveLength(30)
  await wrapper.get('.more-files').trigger('click')
  expect(wrapper.findAll('a')).toHaveLength(60)
  await wrapper.get('input').setValue('sub-109')
  expect(wrapper.findAll('a')).toHaveLength(1)
  expect(wrapper.get('a').text()).toContain('sub-109')
  wrapper.unmount()
})
