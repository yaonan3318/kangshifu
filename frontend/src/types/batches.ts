export type BatchStatus = 'DRAFT'|'UPLOADING'|'PROCESSING'|'PARTIAL_FAILED'|'COMPLETED'|'CANCELLED'
export type BatchUploadStatus = 'PENDING'|'UPLOADING'|'UPLOADED'|'DUPLICATE'|'FAILED'
export type BatchProcessingStatus = 'WAITING'|'PROCESSING'|'PARSED'|'INDEXED'|'FAILED'|'IGNORED'
export interface BatchFileRecord { id:string; document_id:string|null; relative_path:string; original_name:string; size_bytes:number; sha256:string|null; upload_status:BatchUploadStatus; processing_status:BatchProcessingStatus; retry_count:number; error_stage:string|null; error_code:string|null; error_message:string|null; created_at:string; updated_at:string }
export interface BatchRecord { id:string; name:string; category:string|null; tags:string[]; note:string|null; knowledge_base_id:string; status:BatchStatus; total_count:number; indexed_count:number; processing_count:number; duplicate_count:number; failed_count:number; pending_count:number; created_at:string; updated_at:string; completed_at:string|null }
export interface BatchDetail extends BatchRecord { files:BatchFileRecord[] }
export interface BatchList { items:BatchRecord[]; total:number }
export interface BatchCreate { name:string; category?:string|null; tags?:string[]; note?:string|null; knowledge_base_id?:string; files:{relative_path:string;original_name:string;size_bytes:number}[] }
