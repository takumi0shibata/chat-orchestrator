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
        {
          id: "gpt-4.1-mini",
          label: "GPT 4.1 Mini",
          api_mode: "responses",
          supports_temperature: true,
          supports_reasoning_effort: false,
          default_temperature: 0.3,
          default_reasoning_effort: null,
          providerId: "azure_openai",
          providerLabel: "Azure OpenAI",
          providerEnabled: true
        }
      ],
      modelKey: "openai::gpt-5.2",
      onModelChange: vi.fn(),
      skills: [
        { id: "audit", name: "Audit brief", description: "Create action-oriented monitoring notes" },
        { id: "edinet", name: "EDINET Annual Report QA", description: "Answer questions against the filing" }
      ],
      skillId: "audit",
      onSkillChange: vi.fn(),
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
      temperature: 0.3,
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

  it("renders compact triggers and opens the model, skill, and settings popovers", async () => {
    const user = userEvent.setup();
    const props = createProps();

    render(<Composer {...props} />);

    expect(screen.getByLabelText("Message input")).toHaveAttribute("placeholder", "Ask anything");
    expect(screen.getByText("GPT 5.2")).toBeInTheDocument();
    expect(screen.getByText("Audit brief")).toBeInTheDocument();
    expect(screen.getByText("Settings")).toBeInTheDocument();
    expect(screen.getByText("Cmd + Enter to send")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Select model" }));
    expect(screen.getByRole("dialog", { name: "Select model" })).toBeInTheDocument();
    expect(screen.getByText("Azure OpenAI")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Select skill" }));
    expect(screen.getByRole("dialog", { name: "Select skill" })).toBeInTheDocument();
    expect(screen.getByText("No skill")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Open chat settings" }));
    expect(screen.getByRole("dialog", { name: "Chat settings" })).toBeInTheDocument();
    expect(screen.getByLabelText("Temperature")).toBeInTheDocument();
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
