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

export interface AuditNewsAlertV1 {
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

export interface AuditNewsPayloadV1 {
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
  alerts: AuditNewsAlertV1[];
}

export interface AuditNewsViewItemV2 {
  news_id: string;
  title: string;
  summary: string;
  url: string;
  one_liner_comment: string;
  source: string;
  published_at: string;
  view: "self_company" | "peer_companies" | "macro";
  propagation_note: string;
  score: number;
  macro_subtype?: "regulation" | "policy" | "market" | "commodity" | "fx" | "rates";
}

export interface AuditNewsQueryLogV2 {
  stage: string;
  query: string;
  hits: number;
}

export interface AuditNewsDebugStatsV2 {
  raw_counts_by_view?: Record<string, number>;
  deduped_counts_by_view?: Record<string, number>;
  supplemental_runs_by_view?: Record<string, number>;
  dropped_duplicates_by_view?: Record<string, number>;
  query_logs_by_view?: {
    self_company?: AuditNewsQueryLogV2[];
    peer_companies?: AuditNewsQueryLogV2[];
    macro?: AuditNewsQueryLogV2[];
  };
}

export interface AuditNewsPayloadV2 {
  schema: "audit_news_action_brief/v2";
  run_id: string;
  generated_at: string;
  client: {
    name: string;
    industry: string;
    lookback_days: number;
    focus_topics: string[];
    watch_competitors: string[];
    research_profile?: string;
  };
  views: {
    self_company: AuditNewsViewItemV2[];
    peer_companies: AuditNewsViewItemV2[];
    macro: AuditNewsViewItemV2[];
  };
  debug_stats?: AuditNewsDebugStatsV2;
}

export interface AuditNewsViewItemV3 {
  news_id: string;
  title: string;
  summary: string;
  url: string;
  one_liner_comment: string;
  source: string;
  published_at: string;
  view: "self_company" | "peer_companies" | "macro";
}

export interface AuditNewsPayloadV3 {
  schema: "audit_news_action_brief/v3";
  run_id: string;
  generated_at: string;
  client: {
    name: string;
    industry: string;
    lookback_days: number;
    focus_topics: string[];
    watch_competitors: string[];
  };
  views: {
    self_company: AuditNewsViewItemV3[];
    peer_companies: AuditNewsViewItemV3[];
    macro: AuditNewsViewItemV3[];
  };
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
