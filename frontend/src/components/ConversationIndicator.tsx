import type { Conversation } from "../types";

export function ConversationIndicator({ conversation }: { conversation: Conversation }) {
  const active = conversation.active_run;
  const label = active
    ? active.status === "approval_wait" ? "Waiting for approval"
      : active.label?.includes("Waiting for workspace") ? "Waiting for workspace availability"
      : active.label || "Running"
    : conversation.has_unread ? "Unread result" : "";
  if (!label) return null;
  return <span className={`conversation-indicator ${active ? "is-running" : "is-unread"}`}
    role="img" aria-label={label} title={label} />;
}

export function ProjectIndicators({ conversations }: { conversations: Conversation[] }) {
  const running = conversations.filter((c) => c.active_run).length;
  const unread = conversations.filter((c) => c.has_unread).length;
  return <span className="project-indicators">
    {running > 0 && <span className="conversation-indicator is-running" role="img"
      aria-label={`${running} active chats`} title={`${running} active chats`} />}
    {unread > 0 && <span className="conversation-indicator is-unread" role="img"
      aria-label={`${unread} unread results`} title={`${unread} unread results`} />}
  </span>;
}
