import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ConversationSidebar } from "./ConversationSidebar";

describe("ConversationSidebar", () => {
  it("renders the history panel and routes panel actions through callbacks", async () => {
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

    await user.click(screen.getByRole("button", { name: "New chat" }));

    const betaRow = screen.getByText("Beta").closest(".session-item");
    expect(betaRow).not.toBeNull();

    await user.click(within(betaRow as HTMLElement).getAllByRole("button")[0]);
    await user.click(screen.getByRole("button", { name: "Delete Beta" }));
    await user.click(screen.getByRole("button", { name: "Clear history" }));
    await user.click(screen.getByRole("button", { name: "Hide history" }));

    expect(onNewChat).toHaveBeenCalledTimes(1);
    expect(onSelectConversation).toHaveBeenCalledWith("conv-2");
    expect(onDeleteConversation).toHaveBeenCalledWith("conv-2");
    expect(onDeleteAll).toHaveBeenCalledTimes(1);
    expect(onToggleSidebar).toHaveBeenCalledTimes(1);
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
    expect(document.querySelector(".sidebar-panel")?.getAttribute("aria-hidden")).toBe("true");

    await user.click(screen.getByRole("button", { name: "Show history" }));
    expect(onToggleSidebar).toHaveBeenCalledTimes(1);
  });
});
