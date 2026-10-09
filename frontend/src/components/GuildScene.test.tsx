import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { GuildScene } from "./GuildScene";
import { guildDay } from "../lib/guildTime";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  localStorage.clear();
});

it("lets the user pause the scene and remembers the choice after remounting", () => {
  const view = render(<GuildScene />);
  const scene = view.container.querySelector(".guild-scene");
  expect(scene).toHaveAttribute("data-motion", "running");
  fireEvent.click(screen.getByRole("button", { name: "Pause scene animation" }));
  expect(scene).toHaveAttribute("data-motion", "paused");
  view.unmount();
  const remounted = render(<GuildScene />);
  expect(remounted.container.querySelector(".guild-scene")).toHaveAttribute("data-motion", "paused");
  fireEvent.click(screen.getByRole("button", { name: "Resume scene animation" }));
  expect(remounted.container.querySelector(".guild-scene")).toHaveAttribute("data-motion", "running");
});

it("stops offscreen, in hidden tabs and for reduced motion, then releases its observers", () => {
  vi.useFakeTimers();
  let intersection: IntersectionObserverCallback = () => {};
  const disconnect = vi.fn();
  vi.stubGlobal("IntersectionObserver", class {
    constructor(callback: IntersectionObserverCallback) { intersection = callback; }
    observe = vi.fn();
    disconnect = disconnect;
  });
  let preferenceChanged = () => {};
  const media = {
    matches: false,
    addEventListener: vi.fn((_: string, callback: () => void) => { preferenceChanged = callback; }),
    removeEventListener: vi.fn(),
  };
  vi.stubGlobal("matchMedia", vi.fn(() => media));
  const hidden = vi.spyOn(document, "hidden", "get").mockReturnValue(false);
  const removeListener = vi.spyOn(document, "removeEventListener");
  const view = render(<GuildScene />);
  const scene = view.container.querySelector(".guild-scene");
  const inView = (value: boolean) => act(() => intersection([{ isIntersecting: value } as IntersectionObserverEntry], {} as IntersectionObserver));
  expect(scene).toHaveAttribute("data-motion", "paused");
  expect(vi.getTimerCount()).toBe(0);
  inView(true);
  expect(scene).toHaveAttribute("data-motion", "running");
  expect(vi.getTimerCount()).toBe(1);
  hidden.mockReturnValue(true);
  fireEvent(document, new Event("visibilitychange"));
  expect(scene).toHaveAttribute("data-motion", "paused");
  expect(vi.getTimerCount()).toBe(0);
  hidden.mockReturnValue(false);
  fireEvent(document, new Event("visibilitychange"));
  expect(scene).toHaveAttribute("data-motion", "running");
  inView(false);
  expect(scene).toHaveAttribute("data-motion", "paused");
  expect(vi.getTimerCount()).toBe(0);
  vi.setSystemTime(new Date(2026, 9, 9, 22));
  inView(true);
  expect(scene).toHaveAttribute("data-period", "night");
  act(() => { media.matches = true; preferenceChanged(); });
  expect(scene).toHaveAttribute("data-motion", "paused");
  expect(screen.getByRole("button", { name: "Scene motion reduced by system preference" })).toBeDisabled();
  view.unmount();
  expect(vi.getTimerCount()).toBe(0);
  expect(disconnect).toHaveBeenCalledOnce();
  expect(media.removeEventListener).toHaveBeenCalledWith("change", expect.any(Function));
  expect(removeListener).toHaveBeenCalledWith("visibilitychange", expect.any(Function));
});

it.each([
  [8, "morning"], [12, "day"], [18, "evening"], [22, "night"],
] as const)("shows the local scene and Japanese speech at %s:00", (hour, period) => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date(2026, 9, 9, hour));
  const view = render(<GuildScene />);
  expect(view.container.querySelector(".guild-scene")).toHaveAttribute("data-period", period);
  expect(screen.getByText(guildDay[period].label)).toBeInTheDocument();
  const speech = screen.getByRole("button", { name: guildDay[period].comments[0] });
  expect(speech).toHaveAttribute("lang", "ja");
  expect(view.container.querySelector(".guild-tea-steam") !== null).toBe(period === "night");
  fireEvent.click(speech);
  expect(speech).toHaveTextContent(guildDay[period].comments[1]);
});

it("changes at the time boundary without polling, and catches up when focused", () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date(2026, 9, 9, 10, 59, 59));
  const view = render(<GuildScene />);
  const scene = view.container.querySelector(".guild-scene");
  expect(scene).toHaveAttribute("data-period", "morning");
  expect(vi.getTimerCount()).toBe(1);
  act(() => vi.advanceTimersByTime(1000));
  expect(scene).toHaveAttribute("data-period", "day");
  expect(vi.getTimerCount()).toBe(1);
  vi.setSystemTime(new Date(2026, 9, 9, 18));
  fireEvent(window, new Event("focus"));
  expect(scene).toHaveAttribute("data-period", "evening");
  expect(vi.getTimerCount()).toBe(1);
  view.unmount();
  expect(vi.getTimerCount()).toBe(0);
});

it("cycles comments with CSS, pauses automatic speech, and still allows a manual change", () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date(2026, 9, 9, 12));
  render(<GuildScene />);
  const speech = screen.getByTitle("Another comment");
  fireEvent.animationIteration(speech);
  expect(speech).toHaveTextContent(guildDay.day.comments[1]);
  fireEvent.click(screen.getByRole("button", { name: "Pause scene animation" }));
  fireEvent.animationIteration(speech);
  expect(speech).toHaveTextContent(guildDay.day.comments[1]);
  fireEvent.click(speech);
  expect(speech).toHaveTextContent(guildDay.day.comments[2]);
  fireEvent.click(speech);
  expect(speech).toHaveTextContent(guildDay.day.comments[0]);
});
