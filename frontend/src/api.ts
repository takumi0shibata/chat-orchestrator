import type { AgentEvent } from "./types";

export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...options,
    headers: {
      ...(options.body instanceof FormData
        ? {}
        : { "Content-Type": "application/json" }),
      ...options.headers,
    },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(
      typeof body.detail === "string"
        ? body.detail
        : Array.isArray(body.detail)
        ? body.detail.map((item: { loc?: unknown[]; msg?: string }) =>
          `${(item.loc || []).filter((part) => part !== "body").join(".")}: ${item.msg || "Invalid value"}`).join("; ")
        : `Request failed (${response.status})`,
    );
  }
  return response.json();
}

export async function events(
  runId: string,
  after: number,
  signal: AbortSignal,
  receive: (event: AgentEvent) => void,
) {
  const response = await fetch(`/api/runs/${runId}/events?after=${after}`, {
    signal,
  });
  if (!response.ok || !response.body)
    throw new Error("Could not connect to the run history.");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { done, value } = await reader.read();
      buffer += done
        ? decoder.decode()
        : decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";
      for (const line of lines) if (line.trim()) receive(JSON.parse(line));
      if (done) {
        if (buffer.trim()) receive(JSON.parse(buffer));
        break;
      }
    }
  } finally {
    reader.releaseLock();
  }
}
