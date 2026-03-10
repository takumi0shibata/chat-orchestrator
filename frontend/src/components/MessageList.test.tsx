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
            skill_id: null,
            attachments: []
          }
        ]}
        loading={false}
        showThinking={false}
        skillStatus={null}
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
            skill_id: null,
            attachments: []
          },
          {
            role: "user",
            content: "User prompt",
            artifacts: [],
            skill_id: null,
            attachments: []
          }
        ]}
        loading={false}
        showThinking={false}
        skillStatus={null}
        onFeedback={vi.fn()}
      />
    );

    expect(screen.getByText("Assistant reply").closest(".message-panel")).toHaveClass("assistant");
    expect(screen.getByText("User prompt").closest(".message-panel")).toHaveClass("user");
  });

  it("renders user attachment chips without extracted text", () => {
    render(
      <MessageList
        messages={[
          {
            role: "user",
            content: "",
            artifacts: [],
            skill_id: null,
            attachments: [{ id: "att-1", name: "report.pdf", content_type: "application/pdf", size_bytes: 1200 }]
          }
        ]}
        loading={false}
        showThinking={false}
        skillStatus={null}
        onFeedback={vi.fn()}
      />
    );

    expect(screen.getByText("report.pdf")).toBeInTheDocument();
    expect(screen.queryByText("[Attached files]")).not.toBeInTheDocument();
  });

  it("renders a two-line skill activity indicator while a skill is running", () => {
    render(
      <MessageList
        messages={[
          {
            role: "assistant",
            content: "",
            artifacts: [],
            skill_id: "docx_auto_commenter",
            attachments: []
          }
        ]}
        loading
        showThinking={false}
        skillStatus={{
          type: "skill_status",
          status: "running",
          skill_id: "docx_auto_commenter",
          stage: "draft_comments",
          label: "コメント案を生成しています"
        }}
        activeSkillName="DOCX Auto Commenter"
        onFeedback={vi.fn()}
      />
    );

    expect(screen.getByText("DOCX Auto Commenter")).toBeInTheDocument();
    expect(screen.getByText("コメント案を生成しています")).toBeInTheDocument();
  });

  it("falls back to the plain thinking indicator when no skill status is active", () => {
    render(
      <MessageList
        messages={[
          {
            role: "assistant",
            content: "",
            artifacts: [],
            skill_id: null,
            attachments: []
          }
        ]}
        loading
        showThinking
        skillStatus={null}
        onFeedback={vi.fn()}
      />
    );

    expect(screen.getByText("Thinking")).toBeInTheDocument();
  });
});
