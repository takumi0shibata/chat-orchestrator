import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { readAppearance, useAppearance } from "./appearance";

let media: EventTarget & { matches: boolean };
beforeEach(() => {
  localStorage.clear();
  media = Object.assign(new EventTarget(), { matches: true });
  vi.stubGlobal("matchMedia", () => media);
});
afterEach(() => {
  localStorage.clear();
  delete document.documentElement.dataset.theme;
  vi.unstubAllGlobals();
});
it("follows live system changes, overrides them explicitly, and restores the saved choice", () => {
  const { result, unmount } = renderHook(useAppearance);
  expect(result.current[0]).toBe("system");
  expect(document.documentElement.dataset.theme).toBe("dark");
  act(() => { media.matches = false; media.dispatchEvent(new Event("change")); });
  expect(document.documentElement.dataset.theme).toBe("light");
  act(() => result.current[1]("dark"));
  expect(readAppearance()).toBe("dark");
  act(() => media.dispatchEvent(new Event("change")));
  expect(document.documentElement.dataset.theme).toBe("dark");
  unmount();
  const restored = renderHook(useAppearance);
  expect(restored.result.current[0]).toBe("dark");
  act(() => restored.result.current[1]("light"));
  act(() => { media.matches = true; media.dispatchEvent(new Event("change")); });
  expect(document.documentElement.dataset.theme).toBe("light");
  act(() => restored.result.current[1]("system"));
  expect(document.documentElement.dataset.theme).toBe("dark");
});
it("falls back for invalid storage and synchronizes changes from another tab", () => {
  localStorage.setItem("orchestrator-appearance", "unknown");
  const { result } = renderHook(useAppearance);
  expect(result.current[0]).toBe("system");
  act(() => {
    localStorage.setItem("orchestrator-appearance", "light");
    window.dispatchEvent(new StorageEvent("storage", { key: "orchestrator-appearance" }));
  });
  expect(result.current[0]).toBe("light");
  expect(document.documentElement.dataset.theme).toBe("light");
});
it("allows a session preference when storage is unavailable", () => {
  const get = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked"); });
  const set = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("blocked"); });
  const { result } = renderHook(useAppearance);
  expect(result.current[0]).toBe("system");
  act(() => result.current[1]("light"));
  expect(document.documentElement.dataset.theme).toBe("light");
  get.mockRestore();
  set.mockRestore();
});
