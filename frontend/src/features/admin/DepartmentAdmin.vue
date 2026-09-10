<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import {
  createDepartment, disableDepartment, enableDepartment, getDepartmentTree, updateDepartment,
} from '../../api/identity'
import type { DepartmentNode, DepartmentRecord } from '../../types/identity'
import { errorMessage } from '../../utils/errors'

interface FlatNode extends DepartmentRecord { depth: number }

const tree = ref<DepartmentNode[]>([])
const loading = ref(false)
const error = ref('')
const notice = ref('')
const selectedId = ref('')
const saving = ref(false)
const creatingRoot = ref(false)

const form = reactive({ name: '', parent_id: '', enabled: true })

const flat = computed(() => {
  const out: FlatNode[] = []
  const walk = (nodes: DepartmentNode[], depth: number) => {
    for (const node of nodes) {
      const { children, ...rest } = node
      out.push({ ...rest, depth })
      walk(children, depth + 1)
    }
  }
  walk(tree.value, 0)
  return out
})

const selected = computed(() => flat.value.find((node) => node.id === selectedId.value) ?? null)

const parentOptions = computed(() =>
  flat.value.filter((node) => node.id !== selectedId.value && !isDescendant(node.id, selectedId.value)))

function isDescendant(candidateId: string, ancestorId: string): boolean {
  if (!ancestorId) return false
  const findNode = (nodes: DepartmentNode[]): DepartmentNode | null => {
    for (const node of nodes) {
      if (node.id === ancestorId) return node
      const found = findNode(node.children)
      if (found) return found
    }
    return null
  }
  const ancestor = findNode(tree.value)
  if (!ancestor) return false
  const contains = (nodes: DepartmentNode[]): boolean => nodes.some((node) => node.id === candidateId || contains(node.children))
  return contains(ancestor.children)
}

async function refresh() {
  loading.value = true
  error.value = ''
  try {
    tree.value = await getDepartmentTree()
    if (selectedId.value && !flat.value.some((node) => node.id === selectedId.value)) selectedId.value = ''
  } catch (reason) {
    error.value = errorMessage(reason, '无法读取部门树')
  } finally {
    loading.value = false
  }
}

function selectNode(node: FlatNode) {
  selectedId.value = node.id
  creatingRoot.value = false
  form.name = node.name
  form.parent_id = node.parent_id ?? ''
  form.enabled = node.enabled
}

function startCreate(parentId = '') {
  selectedId.value = ''
  creatingRoot.value = true
  form.name = ''
  form.parent_id = parentId
  form.enabled = true
}

async function save() {
  if (!form.name.trim()) { error.value = '请填写部门名称'; return }
  saving.value = true
  error.value = ''
  notice.value = ''
  try {
    if (creatingRoot.value) {
      await createDepartment({ name: form.name.trim(), parent_id: form.parent_id || null, enabled: form.enabled })
      notice.value = '部门已创建'
    } else if (selectedId.value) {
      await updateDepartment(selectedId.value, { name: form.name.trim(), parent_id: form.parent_id || null, enabled: form.enabled })
      notice.value = '部门已更新'
    }
    await refresh()
    creatingRoot.value = false
  } catch (reason) {
    error.value = errorMessage(reason, '保存失败')
  } finally {
    saving.value = false
  }
}

async function toggleEnabled(node: FlatNode) {
  if (node.enabled) {
    const message = node.user_count > 0
      ? `停用“${node.name}”将影响 ${node.user_count} 名用户，且该部门权限资料不再向其开放。确定停用？`
      : `确定停用“${node.name}”？`
    if (!window.confirm(message)) return
    try {
      await disableDepartment(node.id)
      notice.value = '部门已停用'
    } catch (reason) {
      error.value = errorMessage(reason, '停用失败')
    }
  } else {
    try {
      await enableDepartment(node.id)
      notice.value = '部门已启用'
    } catch (reason) {
      error.value = errorMessage(reason, '启用失败')
    }
  }
  await refresh()
}

onMounted(refresh)
</script>

<template>
  <main class="app-shell">
    <header class="hero">
      <p class="eyebrow">SYSTEM · DEPARTMENTS</p>
      <h1>部门管理</h1>
      <p>维护公司部门层级。部门层级向上继承的权限规则与检索权限保持一致。</p>
    </header>
    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="notice" class="assistant-hint">{{ notice }}</p>

    <div class="assistant-grid">
      <section class="assistant-panel">
        <div class="section-heading">
          <div><p class="eyebrow">TREE</p><h2>部门树</h2></div>
          <button type="button" class="primary-action" @click="startCreate('')">＋ 新建根部门</button>
        </div>
        <p v-if="loading" class="assistant-hint">正在加载…</p>
        <ul v-else class="dept-tree">
          <li v-for="node in flat" :key="node.id" :class="{ selected: node.id === selectedId, disabled: !node.enabled }">
            <div class="dept-row" :style="{ paddingLeft: `${node.depth * 20 + 8}px` }">
              <span class="dept-name">{{ node.name }}</span>
              <small>{{ node.user_count }} 人{{ node.enabled ? '' : ' · 已停用' }}</small>
              <span class="row-actions">
                <button type="button" @click="selectNode(node)">编辑</button>
                <button type="button" @click="startCreate(node.id)">新建子部门</button>
                <button type="button" :class="{ 'text-danger': node.enabled }" @click="toggleEnabled(node)">{{ node.enabled ? '停用' : '启用' }}</button>
              </span>
            </div>
          </li>
        </ul>
      </section>

      <section class="assistant-panel">
        <div class="section-heading"><div><p class="eyebrow">EDITOR</p><h2>{{ creatingRoot ? '新建部门' : (selected ? '编辑部门' : '部门详情') }}</h2></div></div>
        <form v-if="creatingRoot || selected" class="assistant-form" @submit.prevent="save">
          <label class="form-row">部门名称<input v-model="form.name" maxlength="255"></label>
          <label class="form-row">上级部门
            <select v-model="form.parent_id">
              <option value="">（无，作为根部门）</option>
              <option v-for="option in parentOptions" :key="option.id" :value="option.id">{{ '　'.repeat(option.depth) }}{{ option.name }}</option>
            </select>
          </label>
          <label class="assistant-checkboxes"><input v-model="form.enabled" type="checkbox">启用部门</label>
          <div class="form-actions">
            <button type="button" class="secondary-action" @click="selectedId = ''; creatingRoot = false">取消</button>
            <button type="submit" :disabled="saving">{{ saving ? '保存中…' : '保存' }}</button>
          </div>
        </form>
        <p v-else class="assistant-hint">从左侧选择部门进行编辑，或新建部门。</p>
      </section>
    </div>
  </main>
</template>
