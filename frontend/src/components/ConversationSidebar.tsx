import type { ConversationSummary } from "../types";
import { PlusIcon, TrashIcon } from "./Icons";

function formatUpdatedAt(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

export function ConversationSidebar(props: {
  sidebarOpen: boolean;
  conversations: ConversationSummary[];
  conversationId: string;
  onNewChat: () => void;
  onDeleteAll: () => void;
  onSelectConversation: (id: string) => void;
  onDeleteConversation: (id: string) => void;
}) {
  const { sidebarOpen, conversations, conversationId, onNewChat, onDeleteAll, onSelectConversation, onDeleteConversation } = props;

  return (
    <aside className={`sidebar ${sidebarOpen ? "" : "closed"}`}>
      <div className="sidebar-header">
        <h1>Orch</h1>
        <div className="sidebar-actions">
          <button className="icon-btn" type="button" title="New chat" onClick={onNewChat}>
            <PlusIcon />
          </button>
          <button className="icon-btn danger" type="button" title="Delete all history" onClick={onDeleteAll}>
            <TrashIcon />
          </button>
        </div>
      </div>

      <div className="session-list">
        {conversations.map((session) => (
          <div key={session.id} className={`session-item ${session.id === conversationId ? "active" : ""}`}>
            <button className="session-main" type="button" onClick={() => onSelectConversation(session.id)}>
              <span className="session-title">{session.title || "New chat"}</span>
              <span className="session-meta">
                {session.message_count} messages • {formatUpdatedAt(session.updated_at)}
              </span>
            </button>
            <button
              className="session-delete"
              type="button"
              title="Delete conversation"
              onClick={() => onDeleteConversation(session.id)}
            >
              <TrashIcon />
            </button>
          </div>
        ))}
      </div>
    </aside>
  );
}
