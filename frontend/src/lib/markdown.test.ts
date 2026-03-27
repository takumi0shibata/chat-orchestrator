import { describe, expect, it } from "vitest";

import { markdownToHtml } from "./markdown";

describe("markdownToHtml", () => {
  it("renders fenced code blocks with explicit language classes", () => {
    const html = markdownToHtml("```python\nprint('hello')\n```\n\n```bash\necho 'world'\n```");
    const root = document.createElement("div");
    root.innerHTML = html;

    expect(root.querySelector(".language-python")?.textContent).toBe("print('hello')\n");
    expect(root.querySelector(".language-bash")?.textContent).toBe("echo 'world'\n");
  });

  it("preserves apostrophes in prose and code output", () => {
    const html = markdownToHtml("We're testing `don't escape`");

    expect(html).toContain("We're testing");
    expect(html).toContain("don't escape");
    expect(html).not.toContain("&#39;");
  });
});
