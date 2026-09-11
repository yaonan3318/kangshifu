<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ApiError } from '../../api/documents'
import {
  compareConfigVersions, compareRuns, createConfigVersion, createDictionaryEntry,
  createEvaluationSet, createSetCase, deleteCase, deleteConfigVersion, deleteDictionaryEntry,
  deleteEvaluationSet, importSetCases, inspectRetrieval, listConfigVersions, listDictionaries,
  listEvaluationSets, listRuns, listSetCases, runEvaluation,
} from '../../api/retrievalLab'
import { listKnowledgeBases } from '../../api/knowledgeBases'
import type {
  ConfigDifference, ConfigVersion, DictionaryEntry, EvaluationSet, RetrievalCase,
  RetrievalInspect, RetrievalRun, RunCompare,
} from '../../types/retrievalLab'
import type { KnowledgeBaseRecord } from '../../types/knowledgeBases'
import RetrievalStages from './RetrievalStages.vue'

// 未列出的字段会继承当前运行时配置；如需覆盖 Query Rewrite 同义词可自行添加。
const DEFAULT_CONFIG_JSON = JSON.stringify({
  keyword_limit: 30, vector_limit: 30, rrf_k: 60, keyword_weight: 1, vector_weight: 1,
  rerank_enabled: false, rerank_model: 'BAAI/bge-reranker-v2-m3', rerank_candidate_limit: 20,
  similarity_threshold: 0.55, min_evidence_score: 0.35, per_document_limit: 3, final_limit: 6,
  query_rewrite_enabled: false, context_completion_enabled: false, context_history_turns: 3,
  multi_query_enabled: false, multi_query_count: 3,
  dictionary_enabled: true, spelling_correction_enabled: true,
}, null, 2)

const bases = ref<KnowledgeBaseRecord[]>([])
const question = ref('')
const knowledgeBaseId = ref('')
const inspection = ref<RetrievalInspect | null>(null)
const busy = ref(false)
const error = ref('')
const notice = ref('')

const sets = ref<EvaluationSet[]>([])
const selectedSetId = ref('')
const cases = ref<RetrievalCase[]>([])
const caseForm = reactive({
  name: '', expectedDocs: '', expectedChunks: '', mustCiteDocs: '', forbiddenDocs: '',
  keypoints: '', expectedNoAnswer: false,
})
const importResult = ref('')

const configs = ref<ConfigVersion[]>([])
const selectedConfigId = ref('')
const configForm = reactive({ name: '', description: '', json: DEFAULT_CONFIG_JSON, isDefault: false })
const diffLeft = ref('')
const diffRight = ref('')
const configDiff = ref<ConfigDifference[]>([])

const runs = ref<RetrievalRun[]>([])
const runLimit = ref(5)
const includeAnswers = ref(false)
const compareLeft = ref('')
const compareRight = ref('')
const comparison = ref<RunCompare | null>(null)

const dictionaries = ref<DictionaryEntry[]>([])
const dictionaryForm = reactive({ category: 'SYNONYM', term: '', expansions: '' })

const selectedSet = computed(() => sets.value.find((item) => item.id === selectedSetId.value) ?? null)
const metricRows = computed(() => {
  if (!runs.value.length) return []
  return Object.entries(runs.value[0].metrics).filter(([, value]) => typeof value === 'number')
})

function splitTokens(value: string): string[] {
  return value.split(/[,，;；|]/).map((item) => item.trim()).filter(Boolean)
}

function parsedConfig(): Record<string, unknown> {
  try { return JSON.parse(configForm.json) } catch { return {} }
}

function configField(name: string): boolean {
  return Boolean(parsedConfig()[name])
}

function configNumber(name: string): number {
  return Number(parsedConfig()[name] ?? 0)
}

function toggleConfigField(name: string) {
  const parsed = parsedConfig()
  parsed[name] = !parsed[name]
  configForm.json = JSON.stringify(parsed, null, 2)
}

function setConfigNumber(name: string, value: number) {
  const parsed = parsedConfig()
  parsed[name] = value
  configForm.json = JSON.stringify(parsed, null, 2)
}

async function load() {
  try {
    const [kb, setList, configList, dictList] = await Promise.all([
      listKnowledgeBases(), listEvaluationSets(), listConfigVersions(), listDictionaries(),
    ])
    bases.value = kb.items
    sets.value = setList
    configs.value = configList
    dictionaries.value = dictList
    if (!selectedSetId.value && sets.value.length) await selectSet(sets.value[0].id)
    if (!selectedConfigId.value) {
      selectedConfigId.value = configs.value.find((item) => item.is_default)?.id ?? configs.value[0]?.id ?? ''
    }
  } catch (reason) {
    error.value = reason instanceof ApiError ? reason.message : '读取检索实验室失败'
  }
}

async function inspect() {
  if (!question.value.trim()) return
  busy.value = true
  error.value = ''
  try {
    inspection.value = await inspectRetrieval(question.value.trim(), knowledgeBaseId.value)
  } catch (reason) {
    error.value = reason instanceof ApiError ? reason.message : '诊断失败'
  } finally {
    busy.value = false
  }
}

async function selectSet(id: string) {
  selectedSetId.value = id
  comparison.value = null
  try {
    cases.value = await listSetCases(id)
    runs.value = await listRuns(id)
  } catch (reason) {
    error.value = reason instanceof ApiError ? reason.message : '读取评测集失败'
  }
}

async function createSet() {
  const name = window.prompt('评测集名称')
  if (!name?.trim()) return
  try {
    const created = await createEvaluationSet({ name: name.trim() })
    await load()
    await selectSet(created.id)
  } catch (reason) {
    error.value = reason instanceof ApiError ? reason.message : '创建评测集失败'
  }
}

async function removeSet(item: EvaluationSet) {
  if (!window.confirm(`删除评测集“${item.name}”及其标准问题？`)) return
  await deleteEvaluationSet(item.id)
  if (selectedSetId.value === item.id) selectedSetId.value = ''
  await load()
}

async function saveCase() {
  if (!selectedSetId.value || !caseForm.name.trim() || !question.value.trim()) {
    error.value = '请先填写用例名称与问题'
    return
  }
  error.value = ''
  try {
    await createSetCase(selectedSetId.value, {
      name: caseForm.name.trim(),
      question: question.value.trim(),
      knowledge_base_id: knowledgeBaseId.value || null,
      expected_document_ids: splitTokens(caseForm.expectedDocs),
      expected_chunk_ids: splitTokens(caseForm.expectedChunks),
      must_cite_document_ids: splitTokens(caseForm.mustCiteDocs),
      forbidden_document_ids: splitTokens(caseForm.forbiddenDocs),
      expected_answer_keypoints: splitTokens(caseForm.keypoints),
      expected_no_answer: caseForm.expectedNoAnswer,
    })
    caseForm.name = ''
    caseForm.expectedDocs = ''
    caseForm.expectedChunks = ''
    caseForm.mustCiteDocs = ''
    caseForm.forbiddenDocs = ''
    caseForm.keypoints = ''
    caseForm.expectedNoAnswer = false
    await selectSet(selectedSetId.value)
    notice.value = '标准问题已保存'
  } catch (reason) {
    error.value = reason instanceof ApiError ? reason.message : '保存用例失败'
  }
}

async function removeCase(item: RetrievalCase) {
  if (!window.confirm(`删除用例“${item.name}”？`)) return
  await deleteCase(item.id)
  await selectSet(selectedSetId.value)
}

async function importCases(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file || !selectedSetId.value) return
  try {
    const result = await importSetCases(selectedSetId.value, file)
    importResult.value = `导入成功 ${result.created} 条，跳过 ${result.skipped} 条`
    if (result.errors.length) importResult.value += `；${result.errors.slice(0, 3).join('；')}`
    await selectSet(selectedSetId.value)
  } catch (reason) {
    error.value = reason instanceof ApiError ? reason.message : '导入失败'
  } finally {
    input.value = ''
  }
}

async function createConfig() {
  if (!configForm.name.trim()) return
  let parsed: Record<string, unknown>
  try {
    parsed = JSON.parse(configForm.json)
  } catch {
    error.value = '配置 JSON 格式不正确'
    return
  }
  try {
    const created = await createConfigVersion({
      name: configForm.name.trim(), description: configForm.description.trim() || null,
      config: parsed, is_default: configForm.isDefault,
    })
    configForm.name = ''
    configForm.description = ''
    await load()
    selectedConfigId.value = created.id
    notice.value = '配置版本已保存'
  } catch (reason) {
    error.value = reason instanceof ApiError ? reason.message : '保存配置版本失败'
  }
}

async function removeConfig(item: ConfigVersion) {
  if (!window.confirm(`删除配置版本“${item.name}”？`)) return
  await deleteConfigVersion(item.id)
  if (selectedConfigId.value === item.id) selectedConfigId.value = ''
  await load()
}

async function saveDictionary() {
  if (!dictionaryForm.term.trim()) return
  try {
    await createDictionaryEntry({
      category: dictionaryForm.category, term: dictionaryForm.term.trim(),
      expansions: splitTokens(dictionaryForm.expansions),
    })
    dictionaryForm.term = ''
    dictionaryForm.expansions = ''
    dictionaries.value = await listDictionaries()
    notice.value = '词典词条已保存'
  } catch (reason) {
    error.value = reason instanceof ApiError ? reason.message : '保存词典失败'
  }
}

async function removeDictionary(item: DictionaryEntry) {
  if (!window.confirm(`删除词条“${item.term}”？`)) return
  await deleteDictionaryEntry(item.id)
  dictionaries.value = await listDictionaries()
}

async function diffConfigs() {
  if (!diffLeft.value || !diffRight.value) return
  try {
    configDiff.value = await compareConfigVersions(diffLeft.value, diffRight.value)
  } catch (reason) {
    error.value = reason instanceof ApiError ? reason.message : '对比配置失败'
  }
}

async function run() {
  if (!selectedSetId.value) return
  busy.value = true
  error.value = ''
  try {
    const result = await runEvaluation({
      evaluation_set_id: selectedSetId.value,
      config_version_id: selectedConfigId.value || null,
      limit: runLimit.value,
      include_answers: includeAnswers.value,
    })
    await selectSet(selectedSetId.value)
    compareRight.value = result.id
    notice.value = '评测已完成'
  } catch (reason) {
    error.value = reason instanceof ApiError ? reason.message : '运行评测失败'
  } finally {
    busy.value = false
  }
}

async function doCompare() {
  if (!compareLeft.value || !compareRight.value) return
  try {
    comparison.value = await compareRuns(compareLeft.value, compareRight.value)
  } catch (reason) {
    error.value = reason instanceof ApiError ? reason.message : '对比运行失败'
  }
}

function formatMetric(value: number | string): string {
  return typeof value === 'number' ? value.toFixed(4) : String(value)
}

function formatMetricValue(value: number, unit: string): string {
  return unit === 'ms' ? `${value.toFixed(1)} ms` : value.toFixed(4)
}

function directionLabel(direction?: string): string {
  if (direction === 'up') return '上升'
  if (direction === 'down') return '下降'
  if (direction === 'same') return '不变'
  if (direction === 'changed') return '已修改'
  return '—'
}

onMounted(load)

onMounted(() => {
  const pending = window.localStorage.getItem('company-search:retrieval-lab-query')
  if (pending) {
    window.localStorage.removeItem('company-search:retrieval-lab-query')
    question.value = pending
    void inspect()
  }
})
</script>

<template>
  <main class="app-shell lab-shell">
    <header class="hero">
      <p class="eyebrow">RETRIEVAL LAB</p>
      <h1>检索实验室</h1>
      <p>观察检索过程，用标准问题集建立可复现的质量基线，并对比不同检索配置版本。</p>
    </header>

    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="notice" class="assistant-hint">{{ notice }}</p>

    <section class="search-panel">
      <div class="lab-query">
        <label>测试问题<textarea v-model="question" placeholder="输入一个真实的公司资料问题"></textarea></label>
        <label>知识库<select v-model="knowledgeBaseId"><option value="">全部知识库</option><option v-for="item in bases" :key="item.id" :value="item.id">{{ item.name }}</option></select></label>
        <button class="primary-action lab-inspect-action" :disabled="busy || !question.trim()" @click="inspect">{{ busy ? '分析中…' : '分析检索过程' }}</button>
      </div>
    </section>

    <section v-if="inspection" class="results-panel">
      <h2>本次检索过程</h2>
      <div v-if="inspection.query_rewrite" class="query-rewrite-box">
        <p class="assistant-hint" style="margin:0 0 6px">查询改写与上下文补全</p>
        <dl>
          <div><dt>原始问题</dt><dd>{{ inspection.query_rewrite.original }}</dd></div>
          <div><dt>补全后问题</dt><dd>{{ inspection.query_rewrite.standalone_question }}</dd></div>
          <div><dt>实际检索问题</dt><dd>{{ inspection.query_rewrite.retrieval_query }}</dd></div>
          <div><dt>是否使用上下文</dt><dd>{{ inspection.query_rewrite.used_context ? '是' : '否' }}</dd></div>
        </dl>
        <p v-if="inspection.queries && inspection.queries.length > 1" class="assistant-hint">
          多查询召回：{{ inspection.queries.join(' ｜ ') }}
        </p>
        <p v-if="inspection.query_rewrite.warning" class="warning-note">{{ inspection.query_rewrite.warning }}</p>
      </div>
      <RetrievalStages :diagnostics="inspection.diagnostics" />
      <div class="admin-table-wrap" style="margin-top:14px">
        <table class="admin-table">
          <thead><tr><th>文档</th><th>片段</th><th>原始分数</th><th>重排前</th><th>重排后</th><th>反馈调整</th><th>最终分数</th></tr></thead>
          <tbody><tr v-for="item in inspection.items" :key="item.chunk_id"><td>{{ item.document_name }}</td><td>{{ item.sequence_number }}</td><td>{{ (item.base_score ?? item.final_score).toFixed(4) }}</td><td>{{ item.pre_rerank_rank ?? '—' }}</td><td>{{ item.post_rerank_rank ?? '—' }}</td><td>{{ (item.feedback_boost ?? 0).toFixed(4) }}</td><td>{{ item.final_score.toFixed(4) }}</td></tr></tbody>
        </table>
      </div>
    </section>

    <section class="results-panel">
      <div class="section-heading">
        <div><p class="eyebrow">EVALUATION SETS</p><h2>评测集</h2></div>
        <button class="primary-action" @click="createSet">＋ 新建评测集</button>
      </div>
      <div class="eval-set-tabs">
        <button v-for="item in sets" :key="item.id" :class="{ active: item.id === selectedSetId }" @click="selectSet(item.id)">
          {{ item.name }}（{{ item.case_count }}）
        </button>
        <button v-if="selectedSet" class="text-danger" @click="removeSet(selectedSet)">删除当前评测集</button>
      </div>

      <template v-if="selectedSet">
        <div class="case-form">
          <input v-model="caseForm.name" placeholder="用例名称">
          <input v-model="caseForm.expectedDocs" placeholder="正确文档（UUID 或文件名，分号分隔）">
          <input v-model="caseForm.expectedChunks" placeholder="期望片段 chunk_id（UUID，分号分隔）">
          <input v-model="caseForm.mustCiteDocs" placeholder="必须引用文档">
          <input v-model="caseForm.forbiddenDocs" placeholder="禁止召回文档">
          <input v-model="caseForm.keypoints" placeholder="答案关键点，分号分隔">
          <label><input v-model="caseForm.expectedNoAnswer" type="checkbox"> 应当无答案</label>
          <button class="primary-action case-save-action" @click="saveCase">保存为评测用例</button>
        </div>
        <label class="import-row">批量导入 CSV/Excel<input type="file" accept=".csv,.xlsx" @change="importCases"></label>
        <p v-if="importResult" class="assistant-hint">{{ importResult }}</p>
        <ul class="governance-list">
          <li v-for="item in cases" :key="item.id">
            <div>
              <strong>{{ item.name }}</strong>
              <small>{{ item.question }} · 正确文档 {{ item.expected_document_ids.length }} · 期望片段 {{ item.expected_chunk_ids.length }} · 必须引用 {{ item.must_cite_document_ids.length }} · 禁止 {{ item.forbidden_document_ids.length }} · 关键点 {{ item.expected_answer_keypoints.length }}</small>
            </div>
            <button class="text-danger" @click="removeCase(item)">删除</button>
          </li>
        </ul>
      </template>
    </section>

    <section class="results-panel">
      <div class="section-heading"><div><p class="eyebrow">RETRIEVAL CONFIG</p><h2>检索配置版本</h2></div></div>
      <div class="config-grid">
        <div class="config-list">
          <ul class="governance-list">
            <li v-for="item in configs" :key="item.id">
              <div>
                <strong>{{ item.name }} <span v-if="item.is_default" class="is-active">默认</span></strong>
                <small>关键词 {{ item.config.keyword_limit }} · 向量 {{ item.config.vector_limit }} · RRF k={{ item.config.rrf_k }} · 精排 {{ item.config.rerank_enabled ? '开' : '关' }} · 最终 {{ item.config.final_limit }}</small>
              </div>
              <button class="text-danger" @click="removeConfig(item)">删除</button>
            </li>
          </ul>
          <div class="config-diff">
            <select v-model="diffLeft"><option value="">版本 A</option><option v-for="item in configs" :key="item.id" :value="item.id">{{ item.name }}</option></select>
            <select v-model="diffRight"><option value="">版本 B</option><option v-for="item in configs" :key="item.id" :value="item.id">{{ item.name }}</option></select>
            <button class="secondary-action" @click="diffConfigs">对比</button>
          </div>
          <table v-if="configDiff.length" class="admin-table">
            <thead><tr><th>参数</th><th>版本 A</th><th>版本 B</th><th>差值</th><th>方向</th></tr></thead>
            <tbody><tr v-for="item in configDiff" :key="item.field"><td>{{ item.label }}</td><td>{{ item.left }}</td><td>{{ item.right }}</td><td>{{ item.delta ?? '—' }}</td><td>{{ directionLabel(item.direction) }}</td></tr></tbody>
          </table>
        </div>
        <form class="config-form" @submit.prevent="createConfig">
          <label>版本名称<input v-model="configForm.name" placeholder="例如 v2-提高召回"></label>
          <label>说明<input v-model="configForm.description" placeholder="本次调整的目的"></label>
          <label>配置 JSON<textarea v-model="configForm.json" rows="10"></textarea></label>
          <div class="config-quick">
            <p class="assistant-hint" style="margin:0">快捷开关（同步到上方 JSON）</p>
            <label class="admin-check-row"><input type="checkbox" :checked="configField('rerank_enabled')" @change="toggleConfigField('rerank_enabled')"><span>启用 Reranker 精排</span></label>
            <label class="admin-check-row"><input type="checkbox" :checked="configField('query_rewrite_enabled')" @change="toggleConfigField('query_rewrite_enabled')"><span>启用 Query Rewrite</span></label>
            <label class="admin-check-row"><input type="checkbox" :checked="configField('context_completion_enabled')" @change="toggleConfigField('context_completion_enabled')"><span>启用多轮上下文补全</span></label>
            <label class="admin-check-row"><input type="checkbox" :checked="configField('multi_query_enabled')" @change="toggleConfigField('multi_query_enabled')"><span>启用 Multi-query</span></label>
            <label class="admin-check-row"><input type="checkbox" :checked="configField('dictionary_enabled')" @change="toggleConfigField('dictionary_enabled')"><span>启用中文词典</span></label>
            <label class="admin-check-row"><input type="checkbox" :checked="configField('spelling_correction_enabled')" @change="toggleConfigField('spelling_correction_enabled')"><span>启用拼写纠正</span></label>
            <label>精排候选<input type="number" min="1" :value="configNumber('rerank_candidate_limit')" @change="setConfigNumber('rerank_candidate_limit', Number(($event.target as HTMLInputElement).value))"></label>
            <label>最终片段<input type="number" min="1" :value="configNumber('final_limit')" @change="setConfigNumber('final_limit', Number(($event.target as HTMLInputElement).value))"></label>
            <label>多查询数量<input type="number" min="2" max="4" :value="configNumber('multi_query_count')" @change="setConfigNumber('multi_query_count', Number(($event.target as HTMLInputElement).value))"></label>
          </div>
          <label class="admin-check-row"><input v-model="configForm.isDefault" type="checkbox"><span>设为默认配置</span></label>
          <div class="config-form-actions"><button type="submit" class="primary-action config-save-action">保存配置版本</button></div>
        </form>
      </div>
    </section>

    <section class="results-panel">
      <div class="section-heading"><div><p class="eyebrow">DICTIONARY</p><h2>中文检索词典</h2></div></div>
      <p class="assistant-hint">同义词 / 公司缩写 / 专有名词由管理员维护，检索时自动扩展，并支持中英文与简称全称互扩。</p>
      <div class="case-form">
        <select v-model="dictionaryForm.category">
          <option value="SYNONYM">同义词</option>
          <option value="ABBREVIATION">缩写/简称</option>
          <option value="PROPER_NOUN">专有名词</option>
          <option value="CROSS_LANGUAGE">中英文映射</option>
        </select>
        <input v-model="dictionaryForm.term" placeholder="词条，如 k8s">
        <input v-model="dictionaryForm.expansions" placeholder="扩展词，分号分隔，如 kubernetes;容器编排">
        <button class="primary-action dictionary-save-action" @click="saveDictionary">保存词条</button>
      </div>
      <ul class="governance-list">
        <li v-for="item in dictionaries" :key="item.id">
          <div>
            <strong>{{ item.term }}</strong>
            <small>{{ { SYNONYM: '同义词', ABBREVIATION: '缩写', PROPER_NOUN: '专有名词', CROSS_LANGUAGE: '中英文映射' }[item.category] }} · {{ item.expansions.join('、') || '无扩展' }} · {{ item.enabled ? '启用' : '停用' }}</small>
          </div>
          <button class="text-danger" @click="removeDictionary(item)">删除</button>
        </li>
      </ul>
    </section>

    <section class="results-panel">
      <div class="section-heading">
        <div><p class="eyebrow">RUNS</p><h2>批量运行评测</h2></div>
        <div class="run-controls">
          <select v-model="selectedConfigId"><option value="">当前运行时配置</option><option v-for="item in configs" :key="item.id" :value="item.id">{{ item.name }}</option></select>
          <label>Top-K<input v-model.number="runLimit" type="number" min="1" max="20"></label>
          <label class="admin-check-row"><input v-model="includeAnswers" type="checkbox"><span>同时生成答案</span></label>
          <button class="primary-action" :disabled="busy || !selectedSetId" @click="run">{{ busy ? '运行中…' : '运行全部评测' }}</button>
        </div>
      </div>

      <div v-if="runs.length" class="admin-table-wrap">
        <table class="admin-table">
          <thead><tr><th>时间</th><th>配置</th><th v-for="[key] in metricRows" :key="key">{{ key }}</th></tr></thead>
          <tbody>
            <tr v-for="item in runs" :key="item.id">
              <td>{{ new Date(item.created_at).toLocaleString('zh-CN') }}</td>
              <td>{{ configs.find((c) => c.id === item.config_version_id)?.name || '运行时配置' }}</td>
              <td v-for="[key] in metricRows" :key="key">{{ formatMetric(item.metrics[key]) }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="config-diff">
        <select v-model="compareLeft"><option value="">旧版本运行</option><option v-for="item in runs" :key="item.id" :value="item.id">{{ new Date(item.created_at).toLocaleString('zh-CN') }}</option></select>
        <select v-model="compareRight"><option value="">新版本运行</option><option v-for="item in runs" :key="item.id" :value="item.id">{{ new Date(item.created_at).toLocaleString('zh-CN') }}</option></select>
        <button class="secondary-action" @click="doCompare">对比两次运行</button>
      </div>

      <template v-if="comparison">
        <h3>指标变化（新 - 旧）</h3>
        <table class="admin-table">
          <thead><tr><th>指标</th><th>旧值</th><th>新值</th><th>差值</th><th>提升 / 下降</th></tr></thead>
          <tbody>
            <tr v-for="item in comparison.metric_changes" :key="item.key">
              <td>{{ item.label }}</td>
              <td>{{ formatMetricValue(item.left, item.unit) }}</td>
              <td>{{ formatMetricValue(item.right, item.unit) }}</td>
              <td :class="{ 'delta-up': item.improved === true, 'delta-down': item.improved === false }">{{ item.delta > 0 ? '+' : '' }}{{ item.delta }}</td>
              <td :class="{ 'delta-up': item.improved === true, 'delta-down': item.improved === false }">
                {{ item.improved === null ? '不变' : (item.improved ? '提升' : '下降') }}
              </td>
            </tr>
          </tbody>
        </table>
        <h3 v-if="comparison.config_differences.length">配置差异</h3>
        <table v-if="comparison.config_differences.length" class="admin-table">
          <thead><tr><th>参数</th><th>旧</th><th>新</th><th>差值</th><th>方向</th></tr></thead>
          <tbody><tr v-for="item in comparison.config_differences" :key="item.field"><td>{{ item.label }}</td><td>{{ item.left }}</td><td>{{ item.right }}</td><td>{{ item.delta ?? '—' }}</td><td>{{ directionLabel(item.direction) }}</td></tr></tbody>
        </table>
      </template>
    </section>
  </main>
</template>
