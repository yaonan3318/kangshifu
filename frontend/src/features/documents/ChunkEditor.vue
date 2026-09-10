<script setup lang="ts">
import { ref } from 'vue'
import { ApiError } from '../../api/documents'
import { reindexChunk, restoreChunk, setChunkEnabled, updateChunk } from '../../api/chunks'
import type { DocumentChunk } from '../../types/documents'
import { hasPermission } from '../../utils/permissions'
const props=defineProps<{chunk:DocumentChunk}>();const emit=defineEmits<{changed:[]}>();const editing=ref(false);const content=ref(props.chunk.content);const busy=ref(false);const error=ref('')
async function action(fn:()=>Promise<unknown>){busy.value=true;error.value='';try{await fn();editing.value=false;emit('changed')}catch(reason){error.value=reason instanceof ApiError?reason.message:'片段操作失败'}finally{busy.value=false}}
</script>
<template><li :class="{'chunk-disabled':chunk.enabled===false}"><div class="chunk-meta"><strong>片段 {{chunk.sequence_number}}</strong><span v-if="chunk.manually_edited">人工修改</span><span v-if="chunk.token_count">{{chunk.token_count}} 词元</span><span>{{chunk.enabled===false?'已停用':'参与检索'}}</span></div><p v-if="error" class="error">{{error}}</p><textarea v-if="editing" v-model="content" class="chunk-textarea"></textarea><pre v-else>{{chunk.content}}</pre><div v-if="hasPermission('DOCUMENT_MANAGE')" class="row-actions"><button @click="editing=!editing">{{editing?'取消':'编辑'}}</button><button v-if="editing" :disabled="busy||!content.trim()" @click="action(()=>updateChunk(chunk.id,content))">保存并重建索引</button><button @click="action(()=>setChunkEnabled(chunk.id,chunk.enabled===false))">{{chunk.enabled===false?'启用':'停用'}}</button><button @click="action(()=>reindexChunk(chunk.id))">重建索引</button><button v-if="chunk.manually_edited" @click="action(()=>restoreChunk(chunk.id))">恢复原文</button></div></li></template>
