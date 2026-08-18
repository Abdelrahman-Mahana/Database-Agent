/* eslint-disable @typescript-eslint/no-explicit-any */

export interface RecommendedQuestion {
  icon?: string;
  title?: string;
  desc?: string;
  query?: string;
}

export interface ColumnMetadata {
  name: string;
  type: string;
  nullable: boolean;
  default?: string | null;
  primary_key: boolean;
  samples?: string[];
  date_range?: string | null;
}

export interface ForeignKeyMetadata {
  constrained_columns: string[];
  referred_schema?: string | null;
  referred_table: string;
  referred_columns: string[];
}

export interface IndexMetadata {
  name: string | null;
  columns: string[];
  unique: boolean;
}

export interface ConstraintMetadata {
  name: string | null;
  type: 'unique' | 'check' | string;
  columns: string[];
  definition?: string | null;
}

export interface BaseDBObject {
  name: string;
  qualified_name: string;
  catalog: string;
  schema: string;
  object_type: 'table' | 'view' | 'procedure' | 'collection' | string;
  columns: ColumnMetadata[];
  primary_key: string[];
  foreign_keys: ForeignKeyMetadata[];
  indexes: IndexMetadata[];
  constraints: ConstraintMetadata[];
  definition?: string | null;
  document_count?: number;
}

export interface SchemaTreeNode {
  id: string;
  kind: 'catalog' | 'schema' | 'folder' | 'table' | 'view' | 'procedure' | 'collection';
  name: string;
  path: string[];
  children?: SchemaTreeNode[];
  meta?: {
    columns?: number;
    indexes?: number;
    foreign_keys?: number;
    constraints?: number;
    document_count?: number;
  };
}

export interface SchemaSummary {
  catalogs: number;
  schemas: number;
  tables: number;
  views: number;
  procedures: number;
  collections: number;
  columns: number;
  indexes: number;
  foreign_keys: number;
  constraints: number;
  objects: number;
}

export interface ActiveProfile {
  db_type: string;
  display_name: string;
  database_name: string;
  masked_url: string;
  ssl_enabled: boolean;
}

export interface SchemaResponse {
  database_name: string;
  database_type: string;
  database_url: string;
  schema_text: string;
  recommended_questions: (string | RecommendedQuestion)[];
  database_schema: Record<string, any>;
  tables: BaseDBObject[];
  views: BaseDBObject[];
  procedures: BaseDBObject[];
  collections: BaseDBObject[];
  schema_tree: SchemaTreeNode[];
  summary: SchemaSummary;
  cache_hit?: boolean;
  connection_id?: string;
  active_profile?: ActiveProfile;
}

export interface ConnectDatabaseResponse {
  name: string;
  filename: string;
  size_mb: number;
}

export interface ConnectionConfigRequest {
  db_type: string;
  display_name?: string;
  connection_url?: string;
  host?: string;
  port?: number;
  database?: string;
  username?: string;
  password?: string;
  file_path?: string;
  ssl_enabled?: boolean;
  ssl_mode?: string;
  options?: Record<string, string>;
  store_credentials?: boolean;
}

export interface ConnectionValidationResponse {
  valid: boolean;
  database_name: string;
  database_type: string;
  summary: SchemaSummary;
}

export interface SavedProfile {
  connection_id: string;
  db_type: string;
  display_name: string;
  database_name: string;
  masked_url: string;
  updated_at: number;
}

export interface ChatRequest {
  message: string;
  session_id?: string;
}

export interface ExecutionMetadata {
  question?: string;
  sql?: string;
  results?: Record<string, any>[];
  chart_suggestion?: {
    should_chart: boolean;
    chart_type: "bar" | "line" | "pie" | "scatter" | string;
    x_column: string;
    y_column: string;
    reason?: string;
  };
  attempted_sql?: string | null;
  error_type?: string | null;
  warnings?: string[] | null;
  suggestions?: string[];
  intent?: string | null;
  analysis_type?: string | null;
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
  quality_score?: number | null;
  confidence_score?: number | null;
  timings_ms?: Record<string, number>;
  schema_metrics?: Record<string, any>;
  llm_trace?: Record<string, any>[];
}

export interface UserResponse {
  answer: string;
  route?: string;
  /** Request lifecycle. `completed` does not necessarily mean the question was answered. */
  request_status: "completed" | "failed";
  /** Semantic outcome for the user's question; use this instead of `success`. */
  answer_status: "answered" | "not_answerable" | "empty_result" | "failed" | "needs_clarification";
  /** @deprecated Use request_status and answer_status instead. */
  success: boolean;
  error?: string | null;
  metadata?: ExecutionMetadata;

  // Legacy flat fields for backward compatibility
  question?: string;
  sql?: string;
  results?: Record<string, any>[];
  report?: string;
  chart_suggestion?: {
    should_chart: boolean;
    chart_type: "bar" | "line" | "pie" | "scatter" | string;
    x_column: string;
    y_column: string;
    reason?: string;
  };
  attempted_sql?: string | null;
  error_type?: string | null;
  warnings?: string[] | null;
  suggestions?: string[];
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
}

export type ChatResponse = UserResponse;

