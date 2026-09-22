import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MarkdownContent } from "./MarkdownContent";

describe("MarkdownContent", () => {
  it("copies literal code from fenced blocks with language tags", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(window.navigator, "clipboard", {
      configurable: true,
      value: { writeText }
    });

    const { container } = render(<MarkdownContent content={"```python\nprint('hello')\n```"} />);

    expect(container.querySelector(".language-python")).not.toBeNull();
    expect(container.querySelector(".code-language")).toHaveTextContent("python");

    fireEvent.click(screen.getByRole("button", { name: "Copy code" }));

    await waitFor(() => expect(writeText).toHaveBeenCalledWith("print('hello')\n"));
    expect(screen.getByRole("button", { name: "Code copied" })).toHaveAttribute("data-state", "copied");
  });

  it("omits a language label for untagged fences and reports copy failures", async () => {
    Object.defineProperty(window.navigator, "clipboard", {
      configurable: true,
      value: { writeText: vi.fn().mockRejectedValue(new Error("denied")) }
    });

    const { container } = render(<MarkdownContent content={"```\necho hello\n```"} />);
    expect(container.querySelector(".code-language")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Copy code" }));

    expect(await screen.findByRole("button", { name: "Copy failed" })).toHaveAttribute("data-state", "failed");
  });
});
