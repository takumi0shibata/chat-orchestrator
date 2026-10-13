import { fireEvent, render, screen, waitFor, cleanup } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ChatGPTConnection } from "./ChatGPTConnection";

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

const connected = { connected: true, plan_usage: true, email: "test@example.com", login_status: "completed", error: null };
it("shows account management without product test controls", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(connected))));
  const back = vi.fn();
  render(<ChatGPTConnection onRefresh={vi.fn()} onBack={back} />);
  await screen.findByText("test@example.com");
  expect(screen.getByText("Connected")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Manage usage ↗" })).toHaveAttribute("href", "https://chatgpt.com/settings/usage");
  expect(screen.queryByText(/Test ChatGPT/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "← Settings" }));
  expect(back).toHaveBeenCalled();
});

it("does not offer inference when plan usage was not granted", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ ...connected, plan_usage: false }))));
  render(<ChatGPTConnection onRefresh={vi.fn()} onBack={vi.fn()} />);
  await screen.findByText(/permission to use your plan is missing/);
  expect(screen.queryByRole("button", { name: "Test ChatGPT response" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Continue with ChatGPT" })).toBeEnabled();
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
  render(<ChatGPTConnection onRefresh={refresh} onBack={vi.fn()} />);
  await waitFor(() => expect(screen.getByRole("button", { name: "Continue with ChatGPT" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "Continue with ChatGPT" }));
  await screen.findByText("Complete sign-in in the browser tab that opened. This page will update automatically.");
  expect(popup.opener).toBeNull();
  expect(popup.location.href).toContain("https://auth.openai.com/");
  fireEvent.click(screen.getByRole("button", { name: "Cancel sign-in" }));
  await waitFor(() => expect(screen.queryByText("Complete sign-in in the browser tab that opened. This page will update automatically.")).not.toBeInTheDocument());
  expect(refresh).toHaveBeenCalled();
});

it("disconnects and refreshes the available providers", async () => {
  const refresh = vi.fn(async () => {});
  vi.stubGlobal("fetch", vi.fn(async (url) => new Response(JSON.stringify(String(url).endsWith("/logout") ? { ...connected, connected: false, plan_usage: false } : connected))));
  render(<ChatGPTConnection onRefresh={refresh} onBack={vi.fn()} />);
  await screen.findByText("test@example.com");
  fireEvent.click(screen.getByRole("button", { name: "Disconnect" }));
  await screen.findByText("Not connected");
  expect(refresh).toHaveBeenCalled();
});
