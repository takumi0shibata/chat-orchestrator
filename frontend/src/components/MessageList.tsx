import type { RefObject } from "react";
import type { ChatMessage, FeedbackAction, FeedbackChoice, StreamAgentEvent, StreamSkillStatus } from "../types";
import { MarkdownContent } from "./MarkdownContent";
import { SkillBlockRenderer } from "./SkillBlockRenderer";

function ThinkingIndicator({ label }: { label: string }) {
  return (
    <div className="thinking" role="status" aria-live="polite">
      <span className="thinking-pulse" aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}

function SkillActivityIndicator(props: {
  skillName: string;
  label: string;
}) {
  const { skillName, label } = props;
  return (
    <div className="skill-activity" role="status" aria-live="polite">
      <div className="skill-activity-header">
        <span className="skill-activity-title">{skillName}</span>
      </div>
      <div className="skill-activity-label">{label}</div>
    </div>
  );
}

function latestAbilityEvent(events: StreamAgentEvent[]) {
  return [...events]
    .reverse()
    .find(
      (
        event
      ): event is Extract<StreamAgentEvent, { type: "ability_started" | "ability_completed" }> =>
        event.type === "ability_started" || event.type === "ability_completed"
    );
}

function abilityProgress(events: StreamAgentEvent[], abilityId: string) {
  const labels: string[] = [];
  for (const event of events) {
    if (event.type !== "agent_status" || event.ability_id !== abilityId) continue;
    if (!event.label.trim() || labels[labels.length - 1] === event.label) continue;
    labels.push(event.label);
  }
  return labels;
}

function AbilityActivityIndicator({ events }: { events: StreamAgentEvent[] }) {
  const latestAbility = latestAbilityEvent(events);
  if (!latestAbility) return null;

  const progress = abilityProgress(events, latestAbility.ability_id);
  const completed = events.find(
    (event): event is Extract<StreamAgentEvent, { type: "ability_completed" }> =>
      event.type === "ability_completed" && event.ability_id === latestAbility.ability_id
  );
  const currentLabel = completed ? "結果を整理しています" : progress[progress.length - 1] || "実行しています";
  const completedSteps = completed ? progress : progress.slice(0, -1);

  return (
    <div className="ability-activity" role="status" aria-live="polite">
      <header className="ability-activity-header">
        <span className="ability-activity-title">{latestAbility.ability_name}</span>
        <span className={`ability-activity-state ${completed ? "done" : "running"}`}>
          {completed ? "完了" : "実行中"}
        </span>
      </header>
      <div className="ability-activity-current">{currentLabel}</div>
      {completedSteps.length > 0 && (
        <ol className="ability-activity-steps">
          {completedSteps.slice(-4).map((label) => (
            <li key={label}>
              <span className="ability-step-dot done" aria-hidden="true" />
              <span>{label}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function AttachmentChips({ attachments }: { attachments: ChatMessage["attachments"] }) {
  if (attachments.length === 0) return null;
  return (
    <div className="attachment-row" aria-label="Attachments">
      {attachments.map((attachment) => (
        <span className="attachment-chip" key={attachment.id}>
          {attachment.name}
        </span>
      ))}
    </div>
  );
}

export function MessageList(props: {
  messages: ChatMessage[];
  loading: boolean;
  showThinking: boolean;
  skillStatus: StreamSkillStatus | null;
  agentTimeline?: StreamAgentEvent[];
  activeSkillName?: string;
  endRef?: RefObject<HTMLDivElement>;
  onFeedback: (action: FeedbackAction, choice: FeedbackChoice) => void;
}) {
  const { messages, loading, showThinking, skillStatus, agentTimeline = [], activeSkillName, endRef, onFeedback } = props;
  const hasAbilityActivity = Boolean(latestAbilityEvent(agentTimeline));

  return (
    <section className="messages">
      {messages.map((message, index) => (
        <article className={`message-row ${message.role}`} key={`${message.role}-${index}`}>
          <div className={`message-panel ${message.role}`}>
            {message.role === "assistant" && loading && hasAbilityActivity && index === messages.length - 1 ? (
              <AbilityActivityIndicator events={agentTimeline} />
            ) : message.role === "assistant" && loading && skillStatus && index === messages.length - 1 ? (
              <SkillActivityIndicator
                skillName={activeSkillName || "Skill"}
                label={skillStatus.label}
              />
            ) : message.role === "assistant" && loading && showThinking && index === messages.length - 1 ? (
              <ThinkingIndicator label="Thinking" />
            ) : message.role === "assistant" ? (
              <div className="assistant-body">
                {message.content.trim() && <MarkdownContent content={message.content} />}
                {message.artifacts.length > 0 && (
                  <div className="assistant-artifacts">
                    <SkillBlockRenderer blocks={message.artifacts} onFeedback={onFeedback} />
                  </div>
                )}
              </div>
            ) : (
              <div className="user-message">
                {message.content.trim() && <p>{message.content}</p>}
                <AttachmentChips attachments={message.attachments} />
              </div>
            )}
          </div>
        </article>
      ))}
      <div ref={endRef} />
    </section>
  );
}
