import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { App } from "./App";

const { controller } = vi.hoisted(() => ({
  controller: {
    skills: [],
    conversations: [
      { id: "conv-1", title: "Quarterly risk review", updated_at: "2026-03-06T10:00:00Z", message_count: 2 }
    ],
    models: [],
    modelKey: "",
    skillId: "",
    temperature: null,
    reasoningEffort: null,
    enableWebTool: false,
    conversationId: "conv-1",
    messages: [],
    input: "",
    attachments: [],
    error: "",
    loading: false,
    showThinking: false,
    showSkillRunning: false,
    sidebarOpen: true,
    selectedModel: {
      id: "gpt-5.2",
      label: "GPT 5.2",
      api_mode: "responses",
      supports_temperature: true,
      supports_reasoning_effort: true,
      default_temperature: 0.3,
      default_reasoning_effort: "medium" as const,
      providerId: "openai",
      providerLabel: "OpenAI",
      providerEnabled: true
    },
    selectedSkill: { id: "audit", name: "Audit brief", description: "desc" },
    canUseWebTool: true,
    setInput: vi.fn(),
    setSkillId: vi.fn(),
    setTemperature: vi.fn(),
    setReasoningEffort: vi.fn(),
    setEnableWebTool: vi.fn(),
    setSidebarOpen: vi.fn(),
    onModelChange: vi.fn(),
    onNewChat: vi.fn(),
    onDeleteConversation: vi.fn(),
    onDeleteAllConversations: vi.fn(),
    onSelectConversation: vi.fn().mockResolvedValue(undefined),
    onAttachFiles: vi.fn(),
    onRemoveAttachment: vi.fn(),
    onCancelStreaming: vi.fn(),
    onSubmitFeedback: vi.fn(),
    onSubmit: vi.fn()
  }
}));

vi.mock("./hooks/useChatController", () => ({
  useChatController: () => controller
}));

vi.mock("./components/ConversationSidebar", () => ({
  ConversationSidebar: () => <div data-testid="sidebar" />
}));

vi.mock("./components/MessageList", () => ({
  MessageList: () => <div data-testid="messages" />
}));

vi.mock("./components/Composer", () => ({
  Composer: () => <div data-testid="composer" />
}));

describe("App", () => {
  it("renders the quiet conversation header without model or mode pills", () => {
    render(<App />);

    expect(screen.getByText("Quarterly risk review")).toBeInTheDocument();
    expect(screen.getByText("2 messages")).toBeInTheDocument();
    expect(screen.queryByText("Model")).not.toBeInTheDocument();
    expect(screen.queryByText("Mode")).not.toBeInTheDocument();
  });
});
