<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { createBatch, uploadBatchFile } from '../../api/batches'
import { ApiError } from '../../api/documents'
import type { KnowledgeBaseRecord } from '../../types/knowledgeBases'
const emit=defineEmits<{created:[id:string]}>()
const props=defineProps<{knowledgeBases:KnowledgeBaseRecord[];knowledgeBaseId:string}>()
const selectedBase=ref(props.knowledgeBaseId)
watch(()=>props.knowledgeBaseId,value=>{if(!selectedBase.value)selectedBase.value=value})
const name=ref(''); const category=ref(''); const tags=ref(''); const note=ref(''); const files=ref<File[]>([]); const busy=ref(false); const error=ref(''); const progress=ref<Record<string,number>>({})
const totalBytes=computed(()=>files.value.reduce((n,f)=>n+f.size,0))
const pathOf=(file:File)=>file.webkitRelativePath||file.name
function select(event:Event){ const input=event.target as HTMLInputElement; files.value=Array.from(input.files||[]); input.value='' }
function formatSize(value:number){ return value<1024**2?`${(value/1024).toFixed(1)} KB`:`${(value/1024**2).toFixed(1)} MB` }
async function submit(){
  if(!name.value.trim()||!files.value.length||busy.value)return; busy.value=true; error.value=''
  try { const batch=await createBatch({name:name.value.trim(),category:category.value||null,tags:tags.value.split(',').map(x=>x.trim()).filter(Boolean),note:note.value||null,knowledge_base_id:selectedBase.value,files:files.value.map(file=>({relative_path:pathOf(file),original_name:file.name,size_bytes:file.size}))})
    let cursor=0; const workers=Array.from({length:Math.min(4,files.value.length)},async()=>{ while(cursor<files.value.length){ const file=files.value[cursor++]; const path=pathOf(file); try { await uploadBatchFile(batch.id,file,path,p=>progress.value[path]=Math.round(p.loaded/p.total*100)) } catch { progress.value[path]=-1 } } })
    await Promise.all(workers); emit('created',batch.id)
  } catch(reason){ error.value=reason instanceof ApiError?reason.message:'无法创建批次' } finally { busy.value=false }
}
</script>
<template><section class="upload-panel batch-import">
  <div class="section-heading"><div><p class="eyebrow">BATCH IMPORT</p><h2>创建导入批次</h2></div><span v-if="files.length">{{files.length}} 个文件 · {{formatSize(totalBytes)}}</span></div>
  <div class="batch-form"><label>目标知识库<select v-model="selectedBase"><option v-for="item in props.knowledgeBases.filter(x=>x.enabled)" :key="item.id" :value="item.id">{{item.name}}</option></select></label><label>批次名称<input v-model="name" placeholder="例如：2026年8月工资资料"></label><label>资料分类<input v-model="category" placeholder="可选"></label><label>标签<input v-model="tags" placeholder="多个标签用逗号分隔"></label><label>备注<input v-model="note" placeholder="可选"></label></div>
  <div class="batch-pickers"><label class="primary-action">选择多个文件<input class="visually-hidden" type="file" multiple @change="select"></label><label class="secondary-action">选择文件夹<input class="visually-hidden" type="file" multiple webkitdirectory @change="select"></label></div>
  <p v-if="error" class="error">{{error}}</p>
  <div v-if="files.length" class="batch-selection"><div v-for="file in files.slice(0,8)" :key="pathOf(file)"><span>{{pathOf(file)}}</span><small>{{progress[pathOf(file)]===-1?'上传失败':progress[pathOf(file)]!=null?`${progress[pathOf(file)]}%`:formatSize(file.size)}}</small></div><p v-if="files.length>8">其余 {{files.length-8}} 个文件将在创建批次后上传</p></div>
  <button class="batch-submit" :disabled="busy||!name.trim()||!files.length" @click="submit">{{busy?'正在导入…':'创建批次并开始上传'}}</button>
</section></template>
