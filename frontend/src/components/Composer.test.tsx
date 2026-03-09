import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Composer } from "./Composer";

describe("Composer", () => {
  function createProps() {
    return {
      input: "Draft request",
      onInputChange: vi.fn(),
      onSubmit: vi.fn((event: { preventDefault: () => void }) => event.preventDefault()),
      attachments: [{ id: "file-1", name: "brief.md", content: "hello" }],
      onAttachFiles: vi.fn(),
      onRemoveAttachment: vi.fn(),
      models: [
        {
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
        {
          id: "gpt-4.1-mini",
          label: "GPT 4.1 Mini",
          api_mode: "responses",
          supports_temperature: true,
          supports_reasoning_effort: false,
          default_temperature: 0.3,
          default_reasoning_effort: null,
          reasoning_effort_options: [],
          providerId: "azure_openai",
          providerLabel: "Azure OpenAI",
          providerEnabled: true
        }
      ],
      modelKey: "openai::gpt-5.4-2026-03-05",
      onModelChange: vi.fn(),
      skills: [
        {
          id: "audit",
          name: "Audit brief",
          description: "Create action-oriented monitoring notes",
          primary_category: { id: "audit", label: "Audit" },
          tags: ["audit", "monitoring"]
        },
        {
          id: "edinet",
          name: "EDINET Annual Report QA",
          description: "Answer questions against the filing",
          primary_category: { id: "finance", label: "Finance" },
          tags: ["finance", "edinet"]
        }
      ],
      skillId: "audit",
      onSkillChange: vi.fn(),
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
      temperature: null,
      onTemperatureChange: vi.fn(),
      reasoningEffort: "medium" as const,
      onReasoningEffortChange: vi.fn(),
      canUseWebTool: true,
      enableWebTool: true,
      onEnableWebToolChange: vi.fn(),
      loading: false,
      conversationId: "conv-1",
      onCancelStreaming: vi.fn()
    };
  }

  it("renders compact triggers and navigates skill categories", async () => {
    const user = userEvent.setup();
    const props = createProps();

    render(<Composer {...props} />);

    expect(screen.getByLabelText("Message input")).toHaveAttribute("placeholder", "Ask anything");
    expect(screen.getByText("GPT 5.4")).toBeInTheDocument();
    expect(screen.getByText("Audit brief")).toBeInTheDocument();
    expect(screen.getByText("Settings")).toBeInTheDocument();
    expect(screen.getByText("Cmd + Enter to send")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Select model" }));
    expect(screen.getByRole("dialog", { name: "Select model" })).toBeInTheDocument();
    expect(screen.getByText("Azure OpenAI")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Select skill" }));
    expect(screen.getByRole("dialog", { name: "Select skill" })).toBeInTheDocument();
    expect(screen.getByText("No skill")).toBeInTheDocument();
    expect(screen.getByText("Audit")).toBeInTheDocument();
    expect(screen.getByText("Finance")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Audit/i }));
    expect(screen.getByText("Create action-oriented monitoring notes")).toBeInTheDocument();
    expect(screen.getByText("monitoring")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Back to skill categories" }));
    expect(screen.getByText("Finance")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Open chat settings" }));
    expect(screen.getByRole("dialog", { name: "Chat settings" })).toBeInTheDocument();
    expect(screen.getByText("Reasoning")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "XHigh" })).toBeInTheDocument();
  });

  it("selects a skill from a category and closes the menu", async () => {
    const user = userEvent.setup();
    const props = createProps();

    render(<Composer {...props} />);

    await user.click(screen.getByRole("button", { name: "Select skill" }));
    await user.click(screen.getByRole("button", { name: /Finance/i }));
    await user.click(screen.getByRole("button", { name: /EDINET Annual Report QA/i }));

    expect(props.onSkillChange).toHaveBeenCalledWith("edinet");
    expect(screen.queryByRole("dialog", { name: "Select skill" })).not.toBeInTheDocument();
  });

  it("shows the cancel action while streaming", () => {
    const props = createProps();

    render(<Composer {...props} loading />);

    expect(screen.getByRole("button", { name: "Cancel generation" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Send message" })).not.toBeInTheDocument();
  });

  it("calls the attachment removal handler from attachment chips", () => {
    const props = createProps();

    render(<Composer {...props} />);

    fireEvent.click(screen.getByRole("button", { name: "Remove brief.md" }));
    expect(props.onRemoveAttachment).toHaveBeenCalledWith("file-1");
  });
});
