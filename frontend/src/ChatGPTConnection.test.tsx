import { fireEvent, render, screen, waitFor, cleanup } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ChatGPTConnection } from "./ChatGPTConnection";

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

const connected = { connected: true, plan_usage: true, email: "test@example.com", login_status: "completed", error: null };
const models = [{ id: "gpt-6-luna", model: "gpt-6-luna", label: "GPT-6 Luna", efforts: ["medium"] }];

it("shows the authorized account and separately tests Responses and native compact", async () => {
  const calls: { url: string; body: unknown }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url, init) => {
    const body = init?.body ? JSON.parse(String(init.body)) : null;
    calls.push({ url: String(url), body });
    return new Response(JSON.stringify(String(url).endsWith("/test") ? { completed: true, text: body.kind === "compact" ? "indigo-42" : "Hello, world!" } : connected));
  }));
  render(<ChatGPTConnection models={models} onRefresh={vi.fn()} />);
  await screen.findByText("test@example.com · Connected");
  fireEvent.click(screen.getByRole("button", { name: "Test ChatGPT response" }));
  await screen.findByText("Test completed · Response: Hello, world!");
  fireEvent.click(screen.getByRole("button", { name: "Test ChatGPT compact" }));
  await screen.findByText("Test completed · Compact + continuation: indigo-42");
  expect(calls.filter((call) => call.url.endsWith("/test")).map((call) => call.body)).toEqual([
    { model: "gpt-6-luna", kind: "response" }, { model: "gpt-6-luna", kind: "compact" },
  ]);
});

it("does not offer inference when plan usage was not granted", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ ...connected, plan_usage: false }))));
  render(<ChatGPTConnection models={models} onRefresh={vi.fn()} />);
  await screen.findByText(/ChatGPT plan usage was not granted/);
  expect(screen.queryByRole("button", { name: "Test ChatGPT response" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Reconnect with ChatGPT" })).toBeEnabled();
});

it("opens the system sign-in flow and cancels a pending attempt", async () => {
  let status = { ...connected, connected: false, plan_usage: false, login_status: "idle" };
  const popup = { opener: {}, location: { href: "" }, close: vi.fn() };
  vi.spyOn(window, "open").mockReturnValue(popup as unknown as Window);
  const refresh = vi.fn(async () => {});
  vi.stubGlobal("fetch", vi.fn(async (url) => {
    if (String(url).endsWith("/login")) {
      status = { ...status, login_status: "pending" };
      return new Response(JSON.stringify({ authorization_url: "https://auth.openai.com/api/accounts/authorize?test=1" }));
    }
    if (String(url).endsWith("/cancel")) status = { ...status, login_status: "idle" };
    return new Response(JSON.stringify(status));
  }));
  render(<ChatGPTConnection models={[]} onRefresh={refresh} />);
  await waitFor(() => expect(screen.getByRole("button", { name: "Continue with ChatGPT" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "Continue with ChatGPT" }));
  await screen.findByText("Complete sign-in in your browser.");
  expect(popup.opener).toBeNull();
  expect(popup.location.href).toContain("https://auth.openai.com/");
  fireEvent.click(screen.getByRole("button", { name: "Cancel sign-in" }));
  await waitFor(() => expect(screen.queryByText("Complete sign-in in your browser.")).not.toBeInTheDocument());
  expect(refresh).toHaveBeenCalled();
});

it("shows compact rejection and allows a later retry", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url) => String(url).endsWith("/test")
    ? new Response(JSON.stringify({ detail: "ChatGPT compact test failed. HTTP 403." }), { status: 502 })
    : new Response(JSON.stringify(connected))));
  render(<ChatGPTConnection models={models} onRefresh={vi.fn()} />);
  await screen.findByText("test@example.com · Connected");
  fireEvent.click(screen.getByRole("button", { name: "Test ChatGPT compact" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("HTTP 403");
  expect(screen.getByRole("button", { name: "Test ChatGPT compact" })).toBeEnabled();
});
