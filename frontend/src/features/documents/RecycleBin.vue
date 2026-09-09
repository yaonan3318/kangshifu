<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ApiError, listDocuments, purgeDocument, restoreDocument } from '../../api/documents'
import type { DocumentRecord } from '../../types/documents'
const emit=defineEmits<{close:[];changed:[]}>(); const items=ref<DocumentRecord[]>([]);const error=ref('');const loading=ref(false)
async function load(){loading.value=true;error.value='';try{items.value=(await listDocuments(new URLSearchParams({deleted:'true',page_size:'100'}))).items}catch(reason){error.value=reason instanceof ApiError?reason.message:'读取回收站失败'}finally{loading.value=false}}
async function restore(item:DocumentRecord){try{await restoreDocument(item.id);await load();emit('changed')}catch(reason){error.value=reason instanceof ApiError?reason.message:'恢复失败'}}
async function purge(item:DocumentRecord){const typed=window.prompt(`永久删除后无法恢复。请输入文件名确认：\n${item.original_name}`);if(typed!==item.original_name)return;try{await purgeDocument(item.id);await load();emit('changed')}catch(reason){error.value=reason instanceof ApiError?reason.message:'永久删除失败'}}
onMounted(load)
</script>
<template><div class="detail-backdrop" @click.self="emit('close')"><section class="detail-panel" role="dialog" aria-modal="true"><header><div><p class="eyebrow">RECYCLE BIN</p><h2>回收站</h2><p>资料永久保留，除非人工永久删除。</p></div><button class="close-button" @click="emit('close')">×</button></header><p v-if="error" class="error">{{error}}</p><p v-if="loading" class="empty">正在读取…</p><p v-else-if="!items.length" class="empty">回收站为空。</p><ul v-else class="governance-list"><li v-for="item in items" :key="item.id"><div><strong>{{item.original_name}}</strong><small>{{item.deleted_reason||'未填写删除原因'}}</small></div><div class="row-actions"><button @click="restore(item)">恢复</button><button class="text-danger" @click="purge(item)">永久删除</button></div></li></ul></section></div></template>
