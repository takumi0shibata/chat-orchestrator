import { afterEach, expect, it, vi } from "vitest";
import { events } from "./api";
afterEach(() => vi.restoreAllMocks());
it("decodes split UTF-8 NDJSON and a final unterminated line", async () => {
  const bytes = new TextEncoder().encode(
    "\n" +
      JSON.stringify({ seq: 4, type: "text_delta", data: { text: "日本語" } }),
  );
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(
      new ReadableStream({
        start(controller) {
          for (const byte of bytes) controller.enqueue(new Uint8Array([byte]));
          controller.close();
        },
      }),
    ),
  );
  const receive = vi.fn();
  await events("r", 3, new AbortController().signal, receive);
  expect(receive).toHaveBeenCalledWith({
    seq: 4,
    type: "text_delta",
    data: { text: "日本語" },
  });
  expect(fetch).toHaveBeenCalledWith(
    "/api/runs/r/events?after=3",
    expect.anything(),
  );
});
