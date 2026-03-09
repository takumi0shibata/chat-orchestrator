import { afterEach, describe, expect, it, vi } from "vitest";

import { extractAttachments, streamChat } from "./api";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("api", () => {
  it("uploads attachments with conversation_id and returns metadata only", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          files: [{ id: "att-1", name: "brief.md", content_type: "text/markdown", size_bytes: 42 }]
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      )
    );
    vi.stubGlobal("fetch", fetchMock);

    const file = new File(["hello"], "brief.md", { type: "text/markdown" });
    const result = await extractAttachments({ conversationId: "conv-1", files: [file] });

    const [, init] = fetchMock.mock.calls[0];
    const body = init?.body as FormData;
    expect(body.get("conversation_id")).toBe("conv-1");
    expect(body.getAll("files")).toHaveLength(1);
    expect(result).toEqual([{ id: "att-1", name: "brief.md", content_type: "text/markdown", size_bytes: 42 }]);
  });

  it("sends attachment_ids separately from user_input during chat streaming", async () => {
    const lines = [
      JSON.stringify({ type: "chunk", delta: "hello " }),
      JSON.stringify({
        type: "done",
        conversation_id: "conv-1",
        provider_id: "openai",
        model: "gpt-5.4-2026-03-05",
        message: {
          role: "assistant",
          content: "hello world",
          artifacts: [],
          skill_id: null,
          attachments: []
        }
      })
    ].join("\n");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(lines, {
        status: 200,
        headers: { "Content-Type": "application/x-ndjson" }
      })
    );
    vi.stubGlobal("fetch", fetchMock);

    const done = await streamChat({
      providerId: "openai",
      model: "gpt-5.4-2026-03-05",
      userInput: "Summarize",
      attachmentIds: ["att-1", "att-2"],
      conversationId: "conv-1",
      onChunk: vi.fn()
    });

    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse(String(init?.body))).toMatchObject({
      user_input: "Summarize",
      attachment_ids: ["att-1", "att-2"],
      conversation_id: "conv-1"
    });
    expect(done.message.attachments).toEqual([]);
  });
});
