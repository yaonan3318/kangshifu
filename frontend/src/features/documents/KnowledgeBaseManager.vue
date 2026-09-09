<script setup lang="ts">
import { ref } from 'vue'
import { ApiError } from '../../api/documents'
import { createKnowledgeBase, setKnowledgeBaseEnabled } from '../../api/knowledgeBases'
import type { KnowledgeBaseRecord } from '../../types/knowledgeBases'

const props=defineProps<{items:KnowledgeBaseRecord[]}>()
const emit=defineEmits<{close:[];changed:[]}>()
const name=ref(''); const description=ref(''); const busy=ref(false); const error=ref('')
async function create(){ if(!name.value.trim())return; busy.value=true; error.value=''; try{ await createKnowledgeBase(name.value.trim(),description.value.trim()); name.value='';description.value='';emit('changed') }catch(reason){error.value=reason instanceof ApiError?reason.message:'创建失败'}finally{busy.value=false} }
async function toggle(item:KnowledgeBaseRecord){ error.value=''; try{await setKnowledgeBaseEnabled(item.id,!item.enabled);emit('changed')}catch(reason){error.value=reason instanceof ApiError?reason.message:'操作失败'} }
</script>
<template><div class="detail-backdrop" @click.self="emit('close')"><section class="detail-panel compact-dialog" role="dialog" aria-modal="true">
  <header><div><p class="eyebrow">KNOWLEDGE BASES</p><h2>管理知识库</h2></div><button class="close-button" @click="emit('close')">×</button></header>
  <p v-if="error" class="error">{{error}}</p>
  <div class="kb-create"><label>名称<input v-model="name" placeholder="例如：技术资料库"></label><label>说明<input v-model="description" placeholder="可选"></label><button :disabled="busy||!name.trim()" @click="create">创建</button></div>
  <ul class="governance-list"><li v-for="item in props.items" :key="item.id"><div><strong>{{item.name}}</strong><small>{{item.description||'暂无说明'}} · {{item.document_count}} 份资料</small></div><button @click="toggle(item)">{{item.enabled?'停用':'启用'}}</button></li></ul>
</section></div></template>
