<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { listChunks } from '../../api/chunks'
import { ApiError, listDocumentVersions, reprocessDocument, updateDocument } from '../../api/documents'
import type { DocumentChunk, DocumentRecord } from '../../types/documents'
import type { KnowledgeBaseRecord } from '../../types/knowledgeBases'
import ChunkEditor from './ChunkEditor.vue'

const props=defineProps<{document:DocumentRecord;knowledgeBases:KnowledgeBaseRecord[]}>();const emit=defineEmits<{close:[];changed:[]}>()
const chunks=ref<DocumentChunk[]>([]);const versions=ref<DocumentRecord[]>([]);const total=ref(0);const page=ref(1);const loading=ref(false);const error=ref('');const tab=ref<'overview'|'chunks'|'versions'>('overview');const tags=ref(props.document.tags.join(','));const targetBase=ref(props.document.knowledge_base_id);const pageSize=10
const pages=computed(()=>Math.max(1,Math.ceil(total.value/pageSize)))
async function load(){loading.value=true;error.value='';try{const [content,history]=await Promise.all([listChunks(props.document.id,page.value,pageSize),listDocumentVersions(props.document.id)]);chunks.value=content.items;total.value=content.total;versions.value=history}catch(reason){error.value=reason instanceof ApiError?reason.message:'无法读取文档详情'}finally{loading.value=false}}
async function saveOverview(){try{await updateDocument(props.document.id,{knowledge_base_id:targetBase.value,tags:tags.value.split(',').map(x=>x.trim()).filter(Boolean)});emit('changed')}catch(reason){error.value=reason instanceof ApiError?reason.message:'保存失败'}}
async function reprocess(){try{await reprocessDocument(props.document.id);emit('changed');emit('close')}catch(reason){if(reason instanceof ApiError&&reason.code==='MANUAL_CHUNKS_WOULD_BE_LOST'&&window.confirm(`${reason.message}，确定继续吗？`)){await fetch(`/api/documents/${props.document.id}/reprocess?confirm_overwrite=true`,{method:'POST'});emit('changed');emit('close')}else error.value=reason instanceof ApiError?reason.message:'重新处理失败'}}
watch(()=>props.document.id,()=>{page.value=1;load()},{immediate:true});watch(page,load)
</script>
<template><div class="detail-backdrop" @click.self="emit('close')"><section class="detail-panel" role="dialog" aria-modal="true"><header><div><p class="eyebrow">DOCUMENT</p><h2>{{document.original_name}}</h2></div><button class="close-button" @click="emit('close')">×</button></header>
  <nav class="detail-tabs"><button :class="{active:tab==='overview'}" @click="tab='overview'">基本信息</button><button :class="{active:tab==='chunks'}" @click="tab='chunks'">片段 {{total}}</button><button :class="{active:tab==='versions'}" @click="tab='versions'">版本历史</button></nav><p v-if="error" class="error">{{error}}</p>
  <section v-if="tab==='overview'" class="detail-section"><dl><div><dt>状态</dt><dd>{{document.status}}</dd></div><div><dt>版本</dt><dd>v{{document.version_number}}</dd></div><div><dt>相对路径</dt><dd>{{document.relative_path||'—'}}</dd></div><div><dt>检索状态</dt><dd>{{document.enabled?'启用':'停用'}}</dd></div></dl><div class="governance-form"><label>知识库<select v-model="targetBase"><option v-for="item in knowledgeBases.filter(x=>x.enabled)" :value="item.id">{{item.name}}</option></select></label><label>标签<input v-model="tags" placeholder="使用逗号分隔"></label><button @click="saveOverview">保存资料设置</button><button @click="reprocess">重新处理</button></div></section>
  <section v-else-if="tab==='chunks'"><p v-if="loading" class="empty">正在读取片段…</p><ol v-else class="chunk-list"><ChunkEditor v-for="chunk in chunks" :key="chunk.id" :chunk="chunk" @changed="load"/></ol><nav v-if="pages>1" class="pagination"><button :disabled="page===1" @click="page--">上一页</button><span>{{page}} / {{pages}}</span><button :disabled="page===pages" @click="page++">下一页</button></nav></section>
  <section v-else><ul class="governance-list"><li v-for="item in versions" :key="item.id"><div><strong>v{{item.version_number}} · {{item.original_name}}</strong><small>{{item.status}} · {{item.enabled?'启用':'停用'}}</small></div></li></ul></section>
</section></div></template>
