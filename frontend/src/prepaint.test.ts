/// <reference types="vite/client" />
import html from "../index.html?raw";
import { afterEach, expect, it, vi } from "vitest";
const script = html.match(/<script>([\s\S]*?)<\/script>/)?.[1] || "";
afterEach(() => { localStorage.clear(); vi.restoreAllMocks(); });
it.each([["dark", false, "dark"], ["light", true, "light"], ["system", true, "dark"], ["invalid", false, "light"]])("sets appearance before module load: %s", (saved, osDark, expected) => {
  document.head.innerHTML = '<meta name="theme-color" content="#fafafa">';
  localStorage.setItem("orchestrator-appearance", String(saved));
  vi.spyOn(window, "matchMedia").mockReturnValue({ matches: osDark } as MediaQueryList);
  expect(script).not.toBe("");
  new Function(script)();
  expect(document.documentElement.dataset.theme).toBe(expected);
  expect(document.querySelector('meta[name="theme-color"]')?.getAttribute("content")).toBe(expected === "dark" ? "#202022" : "#fafafa");
});
