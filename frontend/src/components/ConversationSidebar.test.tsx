import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConversationSidebar } from "./ConversationSidebar";

class MockIntersectionObserver {
  static instances: MockIntersectionObserver[] = [];

  callback: IntersectionObserverCallback;
  target: Element | null = null;

  constructor(callback: IntersectionObserverCallback) {
    this.callback = callback;
    MockIntersectionObserver.instances.push(this);
  }

  observe = vi.fn((target: Element) => {
    this.target = target;
  });

  disconnect = vi.fn();

  unobserve = vi.fn();

  trigger(isIntersecting = true) {
    if (!this.target) return;
    this.callback(
      [
        {
          isIntersecting,
          target: this.target
        } as IntersectionObserverEntry
      ],
      this as unknown as IntersectionObserver
    );
  }
}

function buildConversations(count: number) {
  return Array.from({ length: count }, (_, index) => ({
    id: `conv-${index + 1}`,
    title: `Conversation ${index + 1}`,
    updated_at: "2026-03-06T10:00:00Z",
    message_count: index + 1
  }));
}

beforeEach(() => {
  MockIntersectionObserver.instances = [];
  vi.stubGlobal("IntersectionObserver", MockIntersectionObserver);
});

describe("ConversationSidebar", () => {
  it("renders the simplified history panel and moves clear history into sidebar settings", async () => {
    const user = userEvent.setup();
    const onToggleSidebar = vi.fn();
    const onNewChat = vi.fn();
    const onDeleteAll = vi.fn();
    const onSelectConversation = vi.fn();
    const onDeleteConversation = vi.fn();

    render(
      <ConversationSidebar
        sidebarOpen
        conversationId="conv-1"
        conversations={[
          { id: "conv-1", title: "Alpha", updated_at: "2026-03-06T10:00:00Z", message_count: 3 },
          { id: "conv-2", title: "Beta", updated_at: "2026-03-05T10:00:00Z", message_count: 8 }
        ]}
        onToggleSidebar={onToggleSidebar}
        onNewChat={onNewChat}
        onDeleteAll={onDeleteAll}
        onSelectConversation={onSelectConversation}
        onDeleteConversation={onDeleteConversation}
      />
    );

    expect(screen.getByText("Recent chats")).toBeInTheDocument();
    expect(screen.getByText("Alpha").closest(".session-item")).toHaveClass("active");
    expect(screen.queryByText("Chat workspace")).not.toBeInTheDocument();
    expect(screen.queryByText("2 conversations")).not.toBeInTheDocument();
    expect(document.querySelector(".session-count")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Clear history" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "New chat" }));

    const betaRow = screen.getByText("Beta").closest(".session-item");
    expect(betaRow).not.toBeNull();

    await user.click(within(betaRow as HTMLElement).getAllByRole("button")[0]);
    await user.click(screen.getByRole("button", { name: "Delete Beta" }));
    await user.click(screen.getByRole("button", { name: "Open sidebar settings" }));
    expect(screen.getByRole("dialog", { name: "Sidebar settings" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Clear history" }));
    await user.click(screen.getByRole("button", { name: "Hide history" }));

    expect(onNewChat).toHaveBeenCalledTimes(1);
    expect(onSelectConversation).toHaveBeenCalledWith("conv-2");
    expect(onDeleteConversation).toHaveBeenCalledWith("conv-2");
    expect(onDeleteAll).toHaveBeenCalledTimes(1);
    expect(onToggleSidebar).toHaveBeenCalledTimes(1);
  });

  it("loads more sidebar conversations when the bottom sentinel intersects", async () => {
    render(
      <ConversationSidebar
        sidebarOpen
        conversationId="conv-1"
        conversations={buildConversations(65)}
        onToggleSidebar={vi.fn()}
        onNewChat={vi.fn()}
        onDeleteAll={vi.fn()}
        onSelectConversation={vi.fn()}
        onDeleteConversation={vi.fn()}
      />
    );

    expect(screen.getByText("Conversation 30")).toBeInTheDocument();
    expect(screen.queryByText("Conversation 31")).not.toBeInTheDocument();

    const observer = MockIntersectionObserver.instances[MockIntersectionObserver.instances.length - 1];
    expect(observer).toBeDefined();

    observer?.trigger(true);
    await waitFor(() => expect(screen.getByText("Conversation 31")).toBeInTheDocument());
    expect(screen.getByText("Conversation 60")).toBeInTheDocument();
    expect(screen.queryByText("Conversation 61")).not.toBeInTheDocument();

    observer?.trigger(true);
    await waitFor(() => expect(screen.getByText("Conversation 61")).toBeInTheDocument());
  });

  it("keeps the active conversation rendered even when it falls outside the first batch", () => {
    render(
      <ConversationSidebar
        sidebarOpen
        conversationId="conv-45"
        conversations={buildConversations(65)}
        onToggleSidebar={vi.fn()}
        onNewChat={vi.fn()}
        onDeleteAll={vi.fn()}
        onSelectConversation={vi.fn()}
        onDeleteConversation={vi.fn()}
      />
    );

    expect(screen.getByText("Conversation 45")).toBeInTheDocument();
    expect(screen.queryByText("Conversation 61")).not.toBeInTheDocument();
  });

  it("keeps the rail visible when collapsed so the sidebar can be reopened", async () => {
    const user = userEvent.setup();
    const onToggleSidebar = vi.fn();

    render(
      <ConversationSidebar
        sidebarOpen={false}
        conversationId=""
        conversations={[]}
        onToggleSidebar={onToggleSidebar}
        onNewChat={vi.fn()}
        onDeleteAll={vi.fn()}
        onSelectConversation={vi.fn()}
        onDeleteConversation={vi.fn()}
      />
    );

    expect(screen.getByRole("navigation", { name: "Sidebar rail" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Show history" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "New chat" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open sidebar settings" })).toBeInTheDocument();
    expect(document.querySelector(".sidebar-panel")?.getAttribute("aria-hidden")).toBe("true");

    await user.click(screen.getByRole("button", { name: "Show history" }));
    expect(onToggleSidebar).toHaveBeenCalledTimes(1);
  });
});
