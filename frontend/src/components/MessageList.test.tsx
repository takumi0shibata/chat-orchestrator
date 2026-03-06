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
  });
});
