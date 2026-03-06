import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MessageList } from "./MessageList";

describe("MessageList", () => {
  it("renders legacy assistant messages without artifacts", () => {
    render(
      <MessageList
        messages={[
          {
            role: "assistant",
            content: "## Legacy\n\n- plain content only",
            artifacts: [],
            skill_id: null
          }
        ]}
        loading={false}
        showThinking={false}
        showSkillRunning={false}
        onFeedback={vi.fn()}
      />
    );

    expect(screen.getByText("Legacy")).toBeInTheDocument();
    expect(screen.getByText("plain content only")).toBeInTheDocument();
    expect(screen.getByText("Legacy").closest(".message-row")).toHaveClass("assistant");
  });

  it("keeps user messages visually distinct from assistant messages", () => {
    render(
      <MessageList
        messages={[
          {
            role: "assistant",
            content: "Assistant reply",
            artifacts: [],
            skill_id: null
          },
          {
            role: "user",
            content: "User prompt",
            artifacts: [],
            skill_id: null
          }
        ]}
        loading={false}
        showThinking={false}
        showSkillRunning={false}
        onFeedback={vi.fn()}
      />
    );

    expect(screen.getByText("Assistant reply").closest(".message-panel")).toHaveClass("assistant");
    expect(screen.getByText("User prompt").closest(".message-panel")).toHaveClass("user");
  });
});
