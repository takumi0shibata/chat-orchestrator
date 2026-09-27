import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MarkdownContent } from "./MarkdownContent";

describe("MarkdownContent", () => {
  it("renders saved artifact links and completes streamed equations", () => {
    const { container, rerender } = render(<MarkdownContent conversationId="conversation-1" content={"[結果](file:///workspace/結果.md)\n\n\\(x^2"} />);
    expect(screen.getByRole("link", { name: "結果" })).toHaveAttribute("href", `/api/conversations/conversation-1/download?path=${encodeURIComponent("結果.md")}`);
    expect(screen.getByRole("link", { name: "結果" })).toHaveAttribute("download");
    expect(container.querySelector(".katex")).toBeNull();
    expect(container.textContent).toContain("\\(x^2");

    rerender(<MarkdownContent conversationId="conversation-2" content={"[結果](file:///workspace/結果.md)\n\n\\(x^2\\)"} />);
    expect(screen.getByRole("link", { name: "結果" })).toHaveAttribute("href", `/api/conversations/conversation-2/download?path=${encodeURIComponent("結果.md")}`);
    expect(container.querySelector(".katex")).not.toBeNull();
  });

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
