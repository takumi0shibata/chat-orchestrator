export interface Named {
  id: string;
  label: string;
}
export interface Model {
  id: string;
  model: string;
  label: string;
  efforts: string[];
  max_input_tokens?: number;
  deployment?: string;
  connection_id?: string;
  connection_label?: string;
}
export interface Provider extends Named {
  enabled: boolean;
  models: Model[];
}
export interface Skill extends Named {
  name: string;
  description: string;
}
export interface Config {
  providers: Provider[];
  workspaces: (Named & { path: string })[];
  skills: Skill[];
  resources: Named[];
  mcp_servers: Named[];
  compact_token_threshold?: number;
}
export interface AppSettings {
  title_provider: string;
  title_model: string;
  theme_color: string;
  /** New-chat defaults; null falls back to the app default (GPT-6.1 Sol, Medium). */
  default_provider: string | null;
  default_model: string | null;
  default_effort: string | null;
  default_web_search: boolean;
  monthly_budget_usd: number | null;
}
export interface AppSettingsChange extends Partial<AppSettings> {
  reset_default_model?: boolean;
}
export interface StorageUsage {
  checkpoints: { bytes: number; runs: number; oldest: string | null; orphaned_runs: number };
  attachments: { bytes: number; orphaned_bytes: number; orphaned_conversations: number };
  database: { bytes: number };
}
export interface MonthlyCost {
  month: string;
  usd: number;
}
export interface CostSummary {
  currency: "USD";
  estimated: boolean;
  timezone: "UTC";
  exclusions: string[];
  months: MonthlyCost[];
}
export interface Conversation {
  pinned?: boolean;
  id: string;
  title: string;
  workspace_id: string;
  provider?: string;
  azure_connection_id?: string | null;
  updated_at: string;
}
export interface RunRequest {
  conversation_id: string;
  provider: string;
  model: string;
  reasoning_effort: string;
  input: string;
  attachment_ids: string[];
  direct_attachment_ids: string[];
  skill_ids: string[];
  resource_ids: string[];
  mcp_ids: string[];
  web_search: boolean;
}
export interface RunAttachment {
  id: string;
  name: string;
  size: number;
  content_type: string;
  /** Sent to the model as file or image input, not only placed under /input. */
  direct: boolean;
}
export interface Run {
  id: string;
  conversation_id: string;
  status: string;
  request: RunRequest;
  attachments?: RunAttachment[];
  created_at: string;
  updated_at: string;
}
export interface AgentEvent {
  run_id: string;
  seq: number;
  type: string;
  data: Record<string, unknown>;
  created_at: string;
}
export interface WorkspaceFile {
  name: string;
  path: string;
  directory: boolean;
  size: number;
  ignored?: boolean;
}
export interface Attachment {
  id: string;
  name: string;
  size: number;
  content_type: string;
}
export const terminal = (status: string) =>
  ["completed", "failed", "stopped"].includes(status);
