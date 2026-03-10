import { useEffect, useMemo, useRef, useState } from "react";

import type { ConversationSummary } from "../types";
import { BrandIcon, ComposeIcon, GearIcon, PanelIcon, TrashIcon } from "./Icons";

const SESSION_BATCH_SIZE = 30;
const SESSION_PRELOAD_MARGIN = "0px 0px 160px 0px";

function getInitialVisibleCount(conversations: ConversationSummary[], conversationId: string) {
  const activeIndex = conversations.findIndex((item) => item.id === conversationId);
  if (activeIndex < 0) return Math.min(conversations.length, SESSION_BATCH_SIZE);

  return Math.min(
    conversations.length,
    Math.max(SESSION_BATCH_SIZE, Math.ceil((activeIndex + 1) / SESSION_BATCH_SIZE) * SESSION_BATCH_SIZE)
  );
}

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

  const shellRef = useRef<HTMLDivElement | null>(null);
  const settingsButtonRef = useRef<HTMLButtonElement | null>(null);
  const settingsPopoverRef = useRef<HTMLDivElement | null>(null);
  const sessionListRef = useRef<HTMLDivElement | null>(null);
  const sentinelRef = useRef<HTMLDivElement | null>(null);

  const minimumVisibleCount = useMemo(
    () => getInitialVisibleCount(conversations, conversationId),
    [conversations, conversationId]
  );
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [visibleCount, setVisibleCount] = useState(minimumVisibleCount);

  useEffect(() => {
    setVisibleCount(minimumVisibleCount);
  }, [minimumVisibleCount]);

  useEffect(() => {
    const onPointerDown = (event: MouseEvent) => {
      const target = event.target as Node;
      if (settingsButtonRef.current?.contains(target)) return;
      if (settingsPopoverRef.current?.contains(target)) return;
      setSettingsOpen(false);
    };

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setSettingsOpen(false);
    };

    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, []);

  const renderedCount = Math.max(visibleCount, minimumVisibleCount);
  const visibleConversations = useMemo(
    () => conversations.slice(0, Math.min(conversations.length, renderedCount)),
    [conversations, renderedCount]
  );

  useEffect(() => {
    const root = sessionListRef.current;
    const sentinel = sentinelRef.current;
    if (!root || !sentinel || visibleConversations.length >= conversations.length) return;
    if (typeof IntersectionObserver === "undefined") return;

    const observer = new IntersectionObserver(
      (entries) => {
        if (!entries.some((entry) => entry.isIntersecting)) return;
        setVisibleCount((current) => Math.min(conversations.length, current + SESSION_BATCH_SIZE));
      },
      {
        root,
        rootMargin: SESSION_PRELOAD_MARGIN
      }
    );

    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [conversations.length, visibleConversations.length]);

  return (
    <div ref={shellRef} className={`sidebar-shell ${sidebarOpen ? "open" : "collapsed"}`}>
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

        <div className="rail-spacer" />

        <div className="rail-settings">
          <button
            ref={settingsButtonRef}
            className="rail-action"
            type="button"
            title="Open sidebar settings"
            aria-label="Open sidebar settings"
            aria-expanded={settingsOpen}
            onClick={() => setSettingsOpen((current) => !current)}
          >
            <GearIcon />
          </button>

          {settingsOpen && (
            <div ref={settingsPopoverRef} className="rail-popover" role="dialog" aria-label="Sidebar settings">
              <button
                className="rail-popover-action danger"
                type="button"
                onClick={() => {
                  setSettingsOpen(false);
                  onDeleteAll();
                }}
              >
                <TrashIcon />
                <span>Clear history</span>
              </button>
            </div>
          )}
        </div>
      </nav>

      <aside className={`sidebar-panel ${sidebarOpen ? "open" : "closed"}`} aria-hidden={!sidebarOpen}>
        <header className="sidebar-panel-header">
          <div className="sidebar-panel-copy">
            <h2>Orch</h2>
          </div>
        </header>

        <div className="sidebar-section-header">
          <span>Recent chats</span>
        </div>

        <div ref={sessionListRef} className="session-list">
          {visibleConversations.map((session) => (
            <div key={session.id} className={`session-item ${session.id === conversationId ? "active" : ""}`}>
              <button className="session-main" type="button" onClick={() => onSelectConversation(session.id)}>
                <span className="session-title">{session.title || "New chat"}</span>
                <span className="session-meta">{formatUpdatedAt(session.updated_at)}</span>
              </button>
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

          {visibleConversations.length < conversations.length && (
            <div ref={sentinelRef} className="session-list-sentinel" aria-hidden="true" />
          )}
        </div>
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
