import type { ConversationSummary } from "../types";
import { BrandIcon, ComposeIcon, PanelIcon, TrashIcon } from "./Icons";

function formatUpdatedAt(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;

  const now = new Date();
  const isSameDay =
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate();

  return isSameDay
    ? date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
    : date.toLocaleDateString([], { month: "short", day: "numeric" });
}

export function ConversationSidebar(props: {
  sidebarOpen: boolean;
  conversations: ConversationSummary[];
  conversationId: string;
  onToggleSidebar: () => void;
  onNewChat: () => void;
  onDeleteAll: () => void;
  onSelectConversation: (id: string) => void;
  onDeleteConversation: (id: string) => void;
}) {
  const {
    sidebarOpen,
    conversations,
    conversationId,
    onToggleSidebar,
    onNewChat,
    onDeleteAll,
    onSelectConversation,
    onDeleteConversation
  } = props;

  return (
    <div className={`sidebar-shell ${sidebarOpen ? "open" : "collapsed"}`}>
      <nav className="sidebar-rail" aria-label="Sidebar rail">
        <div className="rail-brand" aria-hidden="true">
          <BrandIcon />
        </div>

        <button
          className="rail-action"
          type="button"
          title={sidebarOpen ? "Hide history" : "Show history"}
          aria-label={sidebarOpen ? "Hide history" : "Show history"}
          onClick={onToggleSidebar}
        >
          <PanelIcon />
        </button>

        <button className="rail-action" type="button" title="New chat" aria-label="New chat" onClick={onNewChat}>
          <ComposeIcon />
        </button>
      </nav>

      <aside className={`sidebar-panel ${sidebarOpen ? "open" : "closed"}`} aria-hidden={!sidebarOpen}>
        <header className="sidebar-panel-header">
          <div className="sidebar-panel-copy">
            <span className="sidebar-panel-eyebrow">Chat workspace</span>
            <h2>Orch</h2>
            <p>{conversations.length} conversations</p>
          </div>
        </header>

        <div className="sidebar-section-header">
          <span>Recent chats</span>
          <span>{conversations.length}</span>
        </div>

        <div className="session-list">
          {conversations.map((session) => (
            <div key={session.id} className={`session-item ${session.id === conversationId ? "active" : ""}`}>
              <button className="session-main" type="button" onClick={() => onSelectConversation(session.id)}>
                <span className="session-title">{session.title || "New chat"}</span>
                <span className="session-meta">{formatUpdatedAt(session.updated_at)}</span>
              </button>
              <span className="session-count">{session.message_count}</span>
              <button
                className="session-delete"
                type="button"
                title="Delete conversation"
                aria-label={`Delete ${session.title || "conversation"}`}
                onClick={() => onDeleteConversation(session.id)}
              >
                <TrashIcon />
              </button>
            </div>
          ))}
        </div>

        <button className="sidebar-secondary-action" type="button" onClick={onDeleteAll}>
          <TrashIcon />
          <span>Clear history</span>
        </button>
      </aside>

      <button
        className={`sidebar-backdrop ${sidebarOpen ? "visible" : ""}`}
        type="button"
        aria-label="Close sidebar"
        onClick={onToggleSidebar}
      />
    </div>
  );
}
