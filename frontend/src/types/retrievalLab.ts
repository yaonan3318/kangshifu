import type { SearchDiagnostics, SearchResult } from './search'
export interface RetrievalInspect {items:SearchResult[];diagnostics:SearchDiagnostics}
export interface RetrievalCase {id:string;name:string;question:string;knowledge_base_id:string|null;expected_document_ids:string[];expected_keywords:string[];expected_no_answer:boolean;enabled:boolean;created_at:string;updated_at:string}
export interface RetrievalRun {id:string;settings_snapshot:Record<string,unknown>;results:Array<Record<string,unknown>>;metrics:{case_count:number;recall_at_k:number;mrr:number;no_answer_accuracy:number;average_latency_ms:number};created_at:string}
