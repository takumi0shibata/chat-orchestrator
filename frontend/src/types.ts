export type Role = "system" | "user" | "assistant";

export interface ChatMessage {
  role: Role;
  content: string;
}

export interface ProviderInfo {
  id: string;
  label: string;
  enabled: boolean;
  default_model: string;
}

export interface ModelInfo {
  id: string;
  label: string;
  api_mode: string;
  supports_temperature: boolean;
  supports_reasoning_effort: boolean;
  default_temperature: number | null;
  default_reasoning_effort: "low" | "medium" | "high" | null;
}

export interface SkillInfo {
  id: string;
  name: string;
  description: string;
}

export type SkillFeedbackDecision = "acted" | "monitor" | "not_relevant";

export interface AuditNewsAlert {
  alert_id: string;
  title: string;
  url: string;
  source: string;
  published_at: string;
  category: string;
  impact_hypothesis: string;
  recommended_audit_action: string;
  priority: "high" | "medium" | "low";
  score: number;
}

export interface AuditNewsPayload {
  schema: "audit_news_action_brief/v1";
  run_id: string;
  generated_at: string;
  client: {
    name: string;
    industry: string;
    lookback_days: number;
    focus_topics: string[];
    watch_competitors: string[];
  };
  alerts: AuditNewsAlert[];
}

export interface AuditNewsMetricsResponse {
  total_alerts: number;
  total_feedback: number;
  acted_count: number;
  action_rate: number;
}

export interface ConversationInfo {
  id: string;
}

export interface ConversationSummary {
  id: string;
  title: string;
  updated_at: string;
  message_count: number;
}

export interface ExtractedAttachment {
  name: string;
  content: string;
}

export interface StreamDone {
  type: "done";
  conversation_id: string;
  provider_id: string;
  model: string;
  skill_output: string | null;
}

export interface StreamChunk {
  type: "chunk";
  delta: string;
}

export interface StreamError {
  type: "error";
  message: string;
}

export interface StreamSkillStatus {
  type: "skill_status";
  status: "running" | "done";
  skill_id: string;
}

export type StreamEvent = StreamChunk | StreamDone | StreamError | StreamSkillStatus;
