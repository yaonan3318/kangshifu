import { describe, expect, it } from 'vitest'
import role from './RoleAdmin.vue?raw'
import assistant from '../assistants/AssistantManager.vue?raw'
import flow from '../assistants/ChatflowManager.vue?raw'

describe('系统管理列表布局', () => {
  it('角色和助手表格在单元格内部承载操作按钮', () => {
    expect(role).toContain('<td class="action-cell"><div class="row-actions">')
    expect(assistant).toContain('<td class="action-cell"><div class="row-actions">')
    expect(role).not.toContain('<td class="row-actions">')
    expect(assistant).not.toContain('<td class="row-actions">')
  })

  it('角色和助手操作列具有明确宽度且不会挤出表格', () => {
    expect(role).toContain('<colgroup class="role-table-columns">')
    expect(assistant).toContain('<colgroup class="assistant-table-columns">')
    expect(role).toContain('<col style="width: 18%">')
    expect(assistant).toContain('<col style="width: 16%">')
  })

  it('流程管理采用全宽列表和按需打开的编辑抽屉', () => {
    expect(flow).toContain('class="assistant-panel chatflow-list-panel"')
    expect(flow).toContain('class="chatflow-editor-backdrop"')
    expect(flow).toContain('class="assistant-panel chatflow-editor-panel"')
    expect(flow).toContain('<table class="admin-table">')
    expect(flow).not.toContain('class="chatflow-layout"')
    expect(flow).not.toContain('window.prompt')
  })
})
