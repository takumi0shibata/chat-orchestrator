import type { RefObject } from "react";
import type { ChatMessage, FeedbackAction, FeedbackChoice, StreamSkillStatus } from "../types";
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
  activeSkillName?: string;
  endRef?: RefObject<HTMLDivElement>;
  onFeedback: (action: FeedbackAction, choice: FeedbackChoice) => void;
}) {
  const { messages, loading, showThinking, skillStatus, activeSkillName, endRef, onFeedback } = props;

  return (
    <section className="messages">
      {messages.map((message, index) => (
        <article className={`message-row ${message.role}`} key={`${message.role}-${index}`}>
          <div className={`message-panel ${message.role}`}>
            {message.role === "assistant" && loading && skillStatus && index === messages.length - 1 ? (
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
