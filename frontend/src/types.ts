export interface Named {
  id: string;
  label: string;
}
export interface Model {
  id: string;
  model: string;
  label: string;
  efforts: string[];
}
export interface Provider extends Named {
  enabled: boolean;
  models: Model[];
}
export interface Config {
  providers: Provider[];
  workspaces: (Named & { path: string })[];
  skills: (Named & { name: string; description: string })[];
  resources: Named[];
  mcp_servers: Named[];
}
export interface Conversation {
  pinned?: boolean;
  id: string;
  title: string;
  workspace_id: string;
  provider?: string;
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
export interface Run {
  id: string;
  conversation_id: string;
  status: string;
  request: RunRequest;
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
}
export interface Attachment {
  id: string;
  name: string;
  size: number;
  content_type: string;
}
export const terminal = (status: string) =>
  ["completed", "failed", "stopped"].includes(status);
