import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useChatController } from "./useChatController";

const apiMocks = vi.hoisted(() => ({
  createConversation: vi.fn(),
  deleteAllConversations: vi.fn(),
  deleteConversation: vi.fn(),
  extractAttachments: vi.fn(),
  fetchConversationMessages: vi.fn(),
  fetchConversations: vi.fn(),
  fetchProviderModels: vi.fn(),
  fetchProviders: vi.fn(),
  fetchSkills: vi.fn(),
  streamChat: vi.fn(),
  submitSkillFeedback: vi.fn()
}));

vi.mock("../api", () => apiMocks);

function createDeferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

async function renderController() {
  const hook = renderHook(() => useChatController());
  await waitFor(() => expect(hook.result.current.conversationId).toBe("conv-1"));
  return hook;
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();

  apiMocks.fetchProviders.mockResolvedValue([
    {
      id: "openai",
      label: "OpenAI",
      enabled: true,
      default_model: "gpt-5.4-2026-03-05"
    }
  ]);
  apiMocks.fetchProviderModels.mockResolvedValue([
    {
      id: "gpt-5.4-2026-03-05",
      label: "GPT 5.4",
      api_mode: "responses",
      supports_temperature: false,
      supports_reasoning_effort: true,
      default_temperature: null,
      default_reasoning_effort: "medium",
      reasoning_effort_options: ["none", "minimal", "low", "medium", "high", "xhigh"]
    }
  ]);
  apiMocks.fetchSkills.mockResolvedValue([]);
  apiMocks.fetchConversations.mockResolvedValue([
    {
      id: "conv-1",
      title: "Existing chat",
      updated_at: "2026-03-06T10:00:00Z",
      message_count: 0
    }
  ]);
  apiMocks.fetchConversationMessages.mockResolvedValue([]);
  apiMocks.createConversation.mockResolvedValue({ id: "conv-new" });
  apiMocks.deleteConversation.mockResolvedValue(undefined);
  apiMocks.deleteAllConversations.mockResolvedValue(undefined);
  apiMocks.extractAttachments.mockResolvedValue([]);
  apiMocks.streamChat.mockResolvedValue({
    type: "done",
    conversation_id: "conv-1",
    provider_id: "openai",
    model: "gpt-5.4-2026-03-05",
    message: {
      role: "assistant",
      content: "",
      artifacts: [],
      skill_id: null,
      attachments: []
    }
  });
  apiMocks.submitSkillFeedback.mockResolvedValue(undefined);
});

describe("useChatController", () => {
  it("turns on attachment parsing state immediately and clears it after a successful single-file parse", async () => {
    const deferred = createDeferred<
      { id: string; name: string; content_type: string; size_bytes: number }[]
    >();
    apiMocks.extractAttachments.mockReturnValueOnce(deferred.promise);
    const { result } = await renderController();
    const file = new File(["data"], "report.pdf", { type: "application/pdf" });

    let attachPromise!: Promise<void>;
    await act(async () => {
      attachPromise = result.current.onAttachFiles([file]);
      await Promise.resolve();
    });

    expect(result.current.isParsingAttachments).toBe(true);
    expect(result.current.parsingAttachmentNames).toEqual(["report.pdf"]);
    expect(result.current.parsingAttachmentLabel).toBe("report.pdf を解析しています");

    deferred.resolve([
      {
        id: "att-1",
        name: "report.pdf",
        content_type: "application/pdf",
        size_bytes: 1200
      }
    ]);

    await act(async () => {
      await attachPromise;
    });

    expect(result.current.isParsingAttachments).toBe(false);
    expect(result.current.parsingAttachmentNames).toEqual([]);
    expect(result.current.parsingAttachmentLabel).toBe("");
    expect(result.current.attachments).toEqual([
      {
        id: "att-1",
        name: "report.pdf",
        content_type: "application/pdf",
        size_bytes: 1200
      }
    ]);
  });

  it("aggregates overlapping attachment parses until the last pending batch completes", async () => {
    const firstDeferred = createDeferred<
      { id: string; name: string; content_type: string; size_bytes: number }[]
    >();
    const secondDeferred = createDeferred<
      { id: string; name: string; content_type: string; size_bytes: number }[]
    >();
    apiMocks.extractAttachments
      .mockReturnValueOnce(firstDeferred.promise)
      .mockReturnValueOnce(secondDeferred.promise);

    const { result } = await renderController();
    const alpha = new File(["a"], "alpha.pdf", { type: "application/pdf" });
    const beta = new File(["b"], "beta.csv", { type: "text/csv" });
    const gamma = new File(["c"], "gamma.docx", {
      type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    });

    let firstPromise!: Promise<void>;
    let secondPromise!: Promise<void>;
    await act(async () => {
      firstPromise = result.current.onAttachFiles([alpha]);
      secondPromise = result.current.onAttachFiles([beta, gamma]);
      await Promise.resolve();
    });

    expect(result.current.isParsingAttachments).toBe(true);
    expect(result.current.parsingAttachmentNames).toEqual(["alpha.pdf", "beta.csv", "gamma.docx"]);
    expect(result.current.parsingAttachmentLabel).toBe("alpha.pdf ほか2件を解析しています");

    firstDeferred.resolve([
      {
        id: "att-1",
        name: "alpha.pdf",
        content_type: "application/pdf",
        size_bytes: 1
      }
    ]);

    await act(async () => {
      await firstPromise;
    });

    expect(result.current.isParsingAttachments).toBe(true);
    expect(result.current.parsingAttachmentNames).toEqual(["beta.csv", "gamma.docx"]);
    expect(result.current.parsingAttachmentLabel).toBe("beta.csv ほか1件を解析しています");

    secondDeferred.resolve([
      {
        id: "att-2",
        name: "beta.csv",
        content_type: "text/csv",
        size_bytes: 2
      },
      {
        id: "att-3",
        name: "gamma.docx",
        content_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        size_bytes: 3
      }
    ]);

    await act(async () => {
      await secondPromise;
    });

    expect(result.current.isParsingAttachments).toBe(false);
    expect(result.current.parsingAttachmentNames).toEqual([]);
    expect(result.current.attachments).toHaveLength(3);
  });

  it("clears attachment parsing state and keeps the error path on parse failure", async () => {
    const deferred = createDeferred<
      { id: string; name: string; content_type: string; size_bytes: number }[]
    >();
    apiMocks.extractAttachments.mockReturnValueOnce(deferred.promise);
    const { result } = await renderController();
    const file = new File(["bad"], "broken.pdf", { type: "application/pdf" });

    let attachPromise!: Promise<void>;
    await act(async () => {
      attachPromise = result.current.onAttachFiles([file]);
      await Promise.resolve();
    });

    expect(result.current.isParsingAttachments).toBe(true);
    expect(result.current.parsingAttachmentLabel).toBe("broken.pdf を解析しています");

    deferred.reject(new Error("parse failed"));

    await act(async () => {
      await attachPromise;
    });

    await waitFor(() => expect(result.current.error).toBe("parse failed"));
    expect(result.current.isParsingAttachments).toBe(false);
    expect(result.current.parsingAttachmentNames).toEqual([]);
    expect(result.current.attachments).toEqual([]);
  });
});
