export type Role = "system" | "user" | "assistant";
export type ReasoningEffort = "none" | "minimal" | "low" | "medium" | "high" | "xhigh";

export interface Badge {
  label: string;
  tone: "neutral" | "low" | "medium" | "high";
}

export interface MetadataItem {
  label: string;
  value: string;
}

export interface CardLine {
  label: string;
  value: string;
}

export interface LinkItem {
  label: string;
  url: string;
}

export interface FeedbackChoice {
  value: string;
  label: string;
}

export interface FeedbackAction {
  type: "feedback";
  run_id: string;
  item_id: string;
  choices: FeedbackChoice[];
  selected: string | null;
}

export interface CardItem {
  id: string;
  title: string;
  badge?: Badge | null;
  metadata: MetadataItem[];
  lines: CardLine[];
  links: LinkItem[];
  actions: FeedbackAction[];
}

export interface CardSection {
  id: string;
  title: string;
  badge?: Badge | null;
  summary?: string | null;
  empty_message?: string | null;
  items: CardItem[];
}

export interface MarkdownBlock {
  type: "markdown";
  content: string;
}

export interface LineChartPoint {
  time: string;
  value: number;
  raw: string | null;
}

export interface LineChartBlock {
  type: "line_chart";
  title: string;
  frequency: string;
  points: LineChartPoint[];
}

export interface CardListBlock {
  type: "card_list";
  title?: string | null;
  sections: CardSection[];
}

export type UiBlock = MarkdownBlock | LineChartBlock | CardListBlock;

export interface ChatMessage {
  role: Role;
  content: string;
  artifacts: UiBlock[];
  skill_id?: string | null;
  attachments: AttachmentSummary[];
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
  default_reasoning_effort: ReasoningEffort | null;
  reasoning_effort_options: ReasoningEffort[];
}

export interface SkillCategoryInfo {
  id: string;
  label: string;
}

export interface SkillInfo {
  id: string;
  name: string;
  description: string;
  primary_category: SkillCategoryInfo;
  tags: string[];
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

export interface AttachmentSummary {
  id: string;
  name: string;
  content_type: string;
  size_bytes: number;
}

export interface StreamDone {
  type: "done";
  conversation_id: string;
  provider_id: string;
  model: string;
  message: ChatMessage;
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
