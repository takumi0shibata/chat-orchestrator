import type {
  ChatMessage,
  ConversationInfo,
  ConversationSummary,
  ExtractedAttachment,
  ModelInfo,
  ProviderInfo,
  SkillInfo,
  StreamDone,
  StreamEvent
} from "./types";

export async function fetchProviders(): Promise<ProviderInfo[]> {
  const response = await fetch("/api/providers");
  if (!response.ok) throw new Error("Failed to load providers");
  return response.json();
}

export async function fetchProviderModels(providerId: string): Promise<ModelInfo[]> {
  const response = await fetch(`/api/providers/${providerId}/models`);
  if (!response.ok) throw new Error("Failed to load models");
  return response.json();
}

export async function fetchSkills(): Promise<SkillInfo[]> {
  const response = await fetch("/api/skills");
  if (!response.ok) throw new Error("Failed to load skills");
  return response.json();
}

export async function fetchConversations(): Promise<ConversationSummary[]> {
  const response = await fetch("/api/conversations");
  if (!response.ok) throw new Error("Failed to load conversations");
  return response.json();
}

export async function createConversation(): Promise<ConversationInfo> {
  const response = await fetch("/api/conversations", { method: "POST" });
  if (!response.ok) throw new Error("Failed to create conversation");
  return response.json();
}

export async function deleteConversation(conversationId: string): Promise<void> {
  const response = await fetch(`/api/conversations/${conversationId}`, { method: "DELETE" });
  if (!response.ok) throw new Error("Failed to delete conversation");
}

export async function deleteAllConversations(): Promise<void> {
  const response = await fetch("/api/conversations", { method: "DELETE" });
  if (!response.ok) throw new Error("Failed to delete all conversations");
}

export async function fetchConversationMessages(conversationId: string): Promise<ChatMessage[]> {
  const response = await fetch(`/api/conversations/${conversationId}/messages`);
  if (!response.ok) throw new Error("Failed to load conversation messages");
  return response.json();
}

export async function extractAttachments(files: File[]): Promise<ExtractedAttachment[]> {
  const formData = new FormData();
  for (const file of files) formData.append("files", file);

  const response = await fetch("/api/attachments/extract", {
    method: "POST",
    body: formData
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || "Failed to extract attachments");
  }

  const data = (await response.json()) as { files: ExtractedAttachment[] };
  return data.files;
}

function parseStreamBuffer(
  buffer: string,
  onEvent: (event: StreamEvent) => void
): { rest: string; done: StreamDone | null } {
  const lines = buffer.split("\n");
  let doneEvent: StreamDone | null = null;

  for (let i = 0; i < lines.length - 1; i += 1) {
    const line = lines[i].trim();
    if (!line) continue;

    const event = JSON.parse(line) as StreamEvent;
    onEvent(event);

    if (event.type === "done") doneEvent = event;
    if (event.type === "error") throw new Error(event.message);
  }

  return {
    rest: lines[lines.length - 1] ?? "",
    done: doneEvent
  };
}

export async function streamChat(params: {
  providerId: string;
  model: string;
  userInput: string;
  conversationId: string;
  skillId?: string;
  temperature?: number | null;
  reasoningEffort?: "low" | "medium" | "high" | null;
  onChunk: (delta: string) => void;
}): Promise<StreamDone> {
  const response = await fetch("/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      provider_id: params.providerId,
      model: params.model,
      user_input: params.userInput,
      conversation_id: params.conversationId,
      skill_id: params.skillId || null,
      temperature: params.temperature ?? null,
      reasoning_effort: params.reasoningEffort ?? null
    })
  });

  if (!response.ok || !response.body) {
    const body = await response.text();
    throw new Error(body || "Streaming request failed");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let doneEvent: StreamDone | null = null;

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const parsed = parseStreamBuffer(buffer, (event) => {
      if (event.type === "chunk") params.onChunk(event.delta);
    });
    buffer = parsed.rest;
    if (parsed.done) doneEvent = parsed.done;
  }

  if (!doneEvent) {
    const parsed = parseStreamBuffer(`${buffer}\n`, (event) => {
      if (event.type === "chunk") params.onChunk(event.delta);
    });
    doneEvent = parsed.done;
  }

  if (!doneEvent) throw new Error("Stream ended without done event");
  return doneEvent;
}
