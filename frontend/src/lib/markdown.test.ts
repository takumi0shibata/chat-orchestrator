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

it("resolves Japanese sandbox artifacts through the conversation download API", () => {
  const html = markdownToHtml("[Word版](sandbox:/workspace/reviews/結果.docx)\n[Markdown版](sandbox:/workspace/reviews/%E7%B5%90%E6%9E%9C.md)", "conversation-1");
  expect(html).toContain('/api/conversations/conversation-1/download?path=reviews%2F%E7%B5%90%E6%9E%9C.docx');
  expect(html).toContain('reviews%2F%E7%B5%90%E6%9E%9C.md');
  expect(html).toContain('download>Word版</a>');
});

it("keeps unsafe or unscoped artifact paths inert", () => {
  for (const path of ["sandbox:/workspace/../secret", "sandbox:/workspace/%2e%2e/secret", "sandbox:/workspace/%2fetc/passwd", "sandbox:/workspace/%00bad", "sandbox:/workspace/%ZZ", "sandbox:/input/file", "javascript:alert(1)"]) {
    expect(markdownToHtml(`[file](${path})`, "conversation-1")).not.toContain('<a ');
  }
  expect(markdownToHtml('[file](sandbox:/workspace/result.md)')).not.toContain('<a ');
});
