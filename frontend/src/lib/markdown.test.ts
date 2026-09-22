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

  it("highlights supported languages and aliases with distinct token classes", () => {
    const cases = [
      { language: "python", code: "for i in range(1, 9):\n    pass", tokens: [".hljs-keyword", ".hljs-built_in", ".hljs-number"] },
      { language: "py", code: "return len(items)", tokens: [".hljs-keyword", ".hljs-built_in"] },
      { language: "javascript", code: "const answer = 42;", tokens: [".hljs-keyword", ".hljs-number"] },
      { language: "json", code: '{"enabled": true}', tokens: [".hljs-attr", ".hljs-literal"] },
      { language: "bash", code: "echo 'hello'", tokens: [".hljs-built_in", ".hljs-string"] },
    ];

    for (const { language, code, tokens } of cases) {
      const root = document.createElement("div");
      root.innerHTML = markdownToHtml(`\`\`\`${language}\n${code}\n\`\`\``);

      for (const token of tokens) expect(root.querySelector(token), `${language} should render ${token}`).not.toBeNull();
      expect(root.querySelector("code")?.textContent).toBe(`${code}\n`);
    }
  });

  it("keeps untagged and unknown-language blocks plain and HTML-safe", () => {
    for (const markdown of ["```\n<script>alert(1)</script>\n```", "```unknown\n<script>alert(1)</script>\n```"]) {
      const root = document.createElement("div");
      root.innerHTML = markdownToHtml(markdown);

      expect(root.querySelector("script")).toBeNull();
      expect(root.querySelector(".hljs-keyword")).toBeNull();
      expect(root.querySelector("code")?.textContent).toContain("<script>alert(1)</script>");
    }
  });

  it("keeps shorter nested fences inside a longer fenced code block", () => {
    const markdown = [
      "Before",
      "",
      "````markdown",
      "```typescript",
      'const message: string = "Hello";',
      "```",
      "````",
      "",
      "After",
    ].join("\n");
    const root = document.createElement("div");
    root.innerHTML = markdownToHtml(markdown);

    expect(root.querySelectorAll(".code-wrap")).toHaveLength(1);
    expect(root.querySelector(".code-language")).toHaveTextContent("markdown");
    expect(root.querySelector("code")?.textContent).toBe('```typescript\nconst message: string = "Hello";\n```\n');
    expect(root.querySelectorAll("p")).toHaveLength(2);
    expect(root.textContent).toContain("Before");
    expect(root.textContent).toContain("After");
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
