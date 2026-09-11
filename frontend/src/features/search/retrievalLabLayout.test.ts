import { describe, expect, it } from 'vitest'
import lab from './RetrievalLab.vue?raw'
import documentDetail from '../documents/DocumentDetail.vue?raw'

describe('检索实验室和资料详情操作层级', () => {
  it('检索实验室的关键操作使用统一按钮样式和表单操作区', () => {
    expect(lab).toContain('class="primary-action lab-inspect-action"')
    expect(lab).toContain('class="primary-action case-save-action"')
    expect(lab).toContain('class="primary-action config-save-action"')
    expect(lab).toContain('class="primary-action dictionary-save-action"')
  })

  it('资料设置使用紧凑操作栏，而不是三个满宽按钮', () => {
    expect(documentDetail).toContain('class="document-settings-actions"')
    expect(documentDetail).toContain('class="primary-action" @click="saveOverview"')
    expect(documentDetail).toContain('class="secondary-action" @click="reprocess"')
  })
})
