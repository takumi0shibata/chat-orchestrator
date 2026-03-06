import type { RefObject } from "react";
import type { ChatMessage, FeedbackAction, FeedbackChoice } from "../types";
import { MarkdownContent } from "./MarkdownContent";
import { SkillBlockRenderer } from "./SkillBlockRenderer";

function ThinkingIndicator({ label }: { label: string }) {
  return (
    <div className="thinking">
      <span>{label}</span>
      <span className="dots">
        <i />
        <i />
        <i />
      </span>
    </div>
  );
}

export function MessageList(props: {
  messages: ChatMessage[];
  loading: boolean;
  showThinking: boolean;
  showSkillRunning: boolean;
  selectedSkillName?: string;
  endRef?: RefObject<HTMLDivElement>;
  onFeedback: (action: FeedbackAction, choice: FeedbackChoice) => void;
}) {
  const { messages, loading, showThinking, showSkillRunning, selectedSkillName, endRef, onFeedback } = props;

  return (
    <section className="messages">
      {messages.map((message, index) => (
        <article className={`bubble ${message.role}`} key={`${message.role}-${index}`}>
          {message.role === "assistant" && loading && showSkillRunning && index === messages.length - 1 ? (
            <ThinkingIndicator label={`${selectedSkillName || "Skill"} running`} />
          ) : message.role === "assistant" && loading && showThinking && index === messages.length - 1 ? (
            <ThinkingIndicator label="Thinking" />
          ) : message.role === "assistant" ? (
            <>
              {message.content.trim() && <MarkdownContent content={message.content} />}
              {message.artifacts.length > 0 && <SkillBlockRenderer blocks={message.artifacts} onFeedback={onFeedback} />}
            </>
          ) : (
            <p>{message.content}</p>
          )}
        </article>
      ))}
      <div ref={endRef} />
    </section>
  );
}
