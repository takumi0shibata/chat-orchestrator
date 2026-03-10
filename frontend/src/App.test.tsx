import { fireEvent, render, screen } from "@testing-library/react";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import type { ChatMessage } from "./types";
import { App } from "./App";

function createMessage(content: string) {
  return {
    role: "assistant" as const,
    content,
    artifacts: [],
    skill_id: null,
    attachments: []
  };
}

function createControllerState() {
  return {
    skills: [],
    conversations: [
      { id: "conv-1", title: "Quarterly risk review", updated_at: "2026-03-06T10:00:00Z", message_count: 2 },
      { id: "conv-2", title: "Budget follow-up", updated_at: "2026-03-05T10:00:00Z", message_count: 1 }
    ],
    models: [],
    modelKey: "",
    skillId: "",
    temperature: null,
    reasoningEffort: null,
    enableWebTool: false,
    conversationId: "conv-1",
    messages: [] as ChatMessage[],
    input: "",
    attachments: [],
    error: "",
    loading: false,
    showThinking: false,
    skillStatus: null,
    sidebarOpen: true,
    selectedModel: {
      id: "gpt-5.4-2026-03-05",
      label: "GPT 5.4",
      api_mode: "responses",
      supports_temperature: false,
      supports_reasoning_effort: true,
      default_temperature: null,
      default_reasoning_effort: "medium" as const,
      reasoning_effort_options: ["none", "minimal", "low", "medium", "high", "xhigh"],
      providerId: "openai",
      providerLabel: "OpenAI",
      providerEnabled: true
    },
    selectedSkill: {
      id: "audit",
      name: "Audit brief",
      description: "desc",
      primary_category: { id: "audit", label: "Audit" },
      tags: ["audit", "monitoring"]
    },
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
  };
}

const { controller, scrollIntoViewMock } = vi.hoisted(() => ({
  controller: {
    skills: [],
    conversations: [
      { id: "conv-1", title: "Quarterly risk review", updated_at: "2026-03-06T10:00:00Z", message_count: 2 },
      { id: "conv-2", title: "Budget follow-up", updated_at: "2026-03-05T10:00:00Z", message_count: 1 }
    ],
    models: [],
    modelKey: "",
    skillId: "",
    temperature: null,
    reasoningEffort: null,
    enableWebTool: false,
    conversationId: "conv-1",
    messages: [] as ChatMessage[],
    input: "",
    attachments: [],
    error: "",
    loading: false,
    showThinking: false,
    skillStatus: null,
    sidebarOpen: true,
    selectedModel: {
      id: "gpt-5.4-2026-03-05",
      label: "GPT 5.4",
      api_mode: "responses",
      supports_temperature: false,
      supports_reasoning_effort: true,
      default_temperature: null,
      default_reasoning_effort: "medium" as const,
      reasoning_effort_options: ["none", "minimal", "low", "medium", "high", "xhigh"],
      providerId: "openai",
      providerLabel: "OpenAI",
      providerEnabled: true
    },
    selectedSkill: {
      id: "audit",
      name: "Audit brief",
      description: "desc",
      primary_category: { id: "audit", label: "Audit" },
      tags: ["audit", "monitoring"]
    },
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
  },
  scrollIntoViewMock: vi.fn()
}));

class ResizeObserverMock {
  observe() {}
  disconnect() {}
  unobserve() {}
}

vi.mock("./hooks/useChatController", () => ({
  useChatController: () => controller
}));

vi.mock("./components/ConversationSidebar", () => ({
  ConversationSidebar: () => <div data-testid="sidebar" />
}));

vi.mock("./components/MessageList", () => ({
  MessageList: ({ endRef }: { endRef?: { current: HTMLDivElement | null } }) => (
    <div data-testid="messages">
      <div ref={endRef}>end</div>
    </div>
  )
}));

vi.mock("./components/Composer", () => ({
  Composer: () => <div data-testid="composer">composer</div>
}));

function setScrollMetrics(node: HTMLElement, scrollTop: number) {
  Object.defineProperty(node, "scrollHeight", { configurable: true, value: 2000 });
  Object.defineProperty(node, "clientHeight", { configurable: true, value: 1000 });
  Object.defineProperty(node, "scrollTop", { configurable: true, writable: true, value: scrollTop });
}

beforeAll(() => {
  Object.defineProperty(window, "ResizeObserver", {
    configurable: true,
    writable: true,
    value: ResizeObserverMock
  });
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
    configurable: true,
    value: scrollIntoViewMock
  });
});

beforeEach(() => {
  Object.assign(controller, createControllerState());
  scrollIntoViewMock.mockClear();
});

describe("App", () => {
  it("renders the quiet conversation header without the message-count subtitle", () => {
    render(<App />);

    expect(screen.getByText("Quarterly risk review")).toBeInTheDocument();
    expect(screen.queryByText("2 messages")).not.toBeInTheDocument();
    expect(screen.queryByText("Model")).not.toBeInTheDocument();
    expect(screen.queryByText("Mode")).not.toBeInTheDocument();
  });

  it("stops forced scrolling after the user scrolls away from the bottom and resumes near the bottom", () => {
    const { rerender } = render(<App />);
    const stage = document.querySelector(".chat-stage");
    expect(stage).not.toBeNull();
    setScrollMetrics(stage as HTMLElement, 920);
    scrollIntoViewMock.mockClear();

    controller.loading = true;
    controller.messages = [createMessage("chunk-1")];
    rerender(<App />);
    expect(scrollIntoViewMock).toHaveBeenCalled();

    (stage as HTMLElement).scrollTop = 400;
    fireEvent.scroll(stage as HTMLElement);
    scrollIntoViewMock.mockClear();

    controller.messages = [createMessage("chunk-2")];
    rerender(<App />);
    expect(scrollIntoViewMock).not.toHaveBeenCalled();

    (stage as HTMLElement).scrollTop = 920;
    fireEvent.scroll(stage as HTMLElement);
    scrollIntoViewMock.mockClear();

    controller.messages = [createMessage("chunk-3")];
    rerender(<App />);
    expect(scrollIntoViewMock).toHaveBeenCalled();
  });

  it("re-enables auto-scroll on a new send and on conversation switch", () => {
    const { rerender } = render(<App />);
    const stage = document.querySelector(".chat-stage");
    expect(stage).not.toBeNull();
    setScrollMetrics(stage as HTMLElement, 920);
    scrollIntoViewMock.mockClear();

    controller.loading = true;
    controller.messages = [createMessage("draft")];
    rerender(<App />);

    (stage as HTMLElement).scrollTop = 300;
    fireEvent.scroll(stage as HTMLElement);
    scrollIntoViewMock.mockClear();

    controller.loading = false;
    rerender(<App />);
    controller.loading = true;
    controller.messages = [createMessage("next run")];
    rerender(<App />);
    expect(scrollIntoViewMock).toHaveBeenCalled();

    (stage as HTMLElement).scrollTop = 300;
    fireEvent.scroll(stage as HTMLElement);
    scrollIntoViewMock.mockClear();

    controller.conversationId = "conv-2";
    controller.messages = [createMessage("other conversation")];
    rerender(<App />);
    expect(scrollIntoViewMock).toHaveBeenCalled();
  });
});
