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

  it("keeps inline code distinct from fenced code", () => {
    const root = document.createElement("div");
    root.innerHTML = markdownToHtml("Use `report.md`\n\n```text\nreport.md\n```");

    expect(root.querySelector("p code")).not.toHaveClass("hljs");
    expect(root.querySelector("pre code")).toHaveClass("hljs");
  });

  it("restores inline code nested inside bold text", () => {
    const html = markdownToHtml("**ラベルと `actual` の整合性を確認する**\n**`src` が `tests` の対象外**\n***`deep`***");
    const root = document.createElement("div");
    root.innerHTML = html;

    expect(root.querySelectorAll("strong")).toHaveLength(3);
    expect(root.querySelectorAll("strong code")).toHaveLength(4);
    expect(root.querySelector("em strong code")).toHaveTextContent("deep");
    expect(root.textContent).toContain("ラベルと actual の整合性を確認する");
    expect(root.textContent).not.toContain("INLINE");
  });

  it("does not treat placeholder-like user text as an internal inline token", () => {
    expect(markdownToHtml("@@INLINE0@@ and `code`")).toContain("@@INLINE0@@");
  });

  it("renders thematic breaks instead of paragraphs or list items", () => {
    const root = document.createElement("div");
    root.innerHTML = markdownToHtml("before\n\n---\n\nafter\n* * *\n___");

    expect(root.querySelectorAll("hr")).toHaveLength(3);
    expect(root.querySelectorAll("p")).toHaveLength(2);
    expect(root.querySelector("ul")).toBeNull();
  });
});

it("resolves Japanese sandbox artifacts through the conversation download API", () => {
  const html = markdownToHtml("[Word版](sandbox:/workspace/reviews/結果.docx)\n[Markdown版](sandbox:/workspace/reviews/%E7%B5%90%E6%9E%9C.md)", "conversation-1");
  expect(html).toContain('/api/conversations/conversation-1/download?path=reviews%2F%E7%B5%90%E6%9E%9C.docx');
  expect(html).toContain('reviews%2F%E7%B5%90%E6%9E%9C.md');
  const root = document.createElement("div");
  root.innerHTML = html;
  expect(root.querySelector("a")).toHaveAttribute("download");
  expect(root.querySelector("a")).toHaveTextContent("Word版");
});

it("keeps unsafe or unscoped artifact paths inert", () => {
  for (const path of ["sandbox:/workspace/../secret", "sandbox:/workspace/%2e%2e/secret", "sandbox:/workspace/%2fetc/passwd", "sandbox:/workspace/%00bad", "sandbox:/workspace/%ZZ", "sandbox:/input/file", "javascript:alert(1)"]) {
    expect(markdownToHtml(`[file](${path})`, "conversation-1")).not.toContain('<a ');
  }
  expect(markdownToHtml('[file](sandbox:/workspace/result.md)')).not.toContain('<a ');
});

describe("artifact links", () => {
  function render(markdown: string, conversationId = "conversation-1") {
    const root = document.createElement("div");
    root.innerHTML = markdownToHtml(markdown, conversationId);
    return root;
  }

  it.each([
    "sandbox:/workspace/レビュー結果.md",
    "file:///workspace/レビュー結果.md",
    "/workspace/レビュー結果.md",
    "レビュー結果.md",
    "./レビュー結果.md",
  ])("downloads workspace files from %s", (url) => {
    const link = render(`[結果](${url})`).querySelector("a");
    expect(link).toHaveAttribute("href", `/api/conversations/conversation-1/download?path=${encodeURIComponent("レビュー結果.md")}`);
    expect(link).toHaveAttribute("download");
    expect(link).not.toHaveAttribute("target");
  });

  it.each([
    "<sandbox:/workspace/reviews/結果 (最終).docx>",
    "file:///workspace/reviews/結果%20(最終).docx",
    "reviews/結果%20%28最終%29.docx",
  ])("preserves spaces, parentheses and inline code labels: %s", (url) => {
    const link = render(`[\`結果.docx\`](${url})`).querySelector("a");
    expect(link).toHaveAttribute("href", `/api/conversations/conversation-1/download?path=${encodeURIComponent("reviews/結果 (最終).docx")}`);
    expect(link?.querySelector("code")).toHaveTextContent("結果.docx");
  });

  it("supports reference links and encodes the conversation independently", () => {
    const link = render("[report][file]\n\n[file]: sandbox:/workspace/report.md", "conversation /2").querySelector("a");
    expect(link).toHaveAttribute("href", "/api/conversations/conversation%20%2F2/download?path=report.md");
  });

  it.each([
    "file:///etc/passwd", "file://other/workspace/report.md", "/etc/passwd",
    "../secret", "reports/../secret", "reports/%2e%2e/secret", "%2fetc/passwd",
    "sandbox:/input/file", "sandbox:/workspace/%ZZ", "report%ZZ.md",
    "javascript:alert(1)", "javascript%3Aalert(1)", "data:text/html,bad",
    "//evil.example/report.md", "report.md?path=secret", "report.md#fragment",
    "sandbox:/workspace/%5csecret", "sandbox:/workspace/%00secret",
  ])("does not render unsafe links: %s", (url) => {
    expect(render(`[file](${url})`).querySelector("a")).toBeNull();
  });

  it("keeps external links in a separate tab and escapes raw HTML", () => {
    const root = render('[web](https://example.com/a?q=1&x=2)\n<script>alert(1)</script>');
    expect(root.querySelector("a")).toHaveAttribute("target", "_blank");
    expect(root.querySelector("a")).toHaveAttribute("rel", "noreferrer");
    expect(root.querySelector("a")).not.toHaveAttribute("download");
    expect(root.querySelector("script")).toBeNull();
    expect(root.textContent).toContain("<script>alert(1)</script>");
  });

  it("does not linkify paths inside inline or fenced code", () => {
    const root = render("`[file](report.md)`\n\n```markdown\n[file](report.md)\n```");
    expect(root.querySelector("a")).toBeNull();
  });
});

describe("LaTeX math", () => {
  function render(markdown: string) {
    const root = document.createElement("div");
    root.innerHTML = markdownToHtml(markdown, "conversation-1");
    return root;
  }

  it.each(["$x^2$", String.raw`\(x^2\)`])("renders inline math: %s", (input) => {
    const root = render(`式は${input}です。`);
    expect(root.querySelector("p .katex")).not.toBeNull();
    expect(root.querySelector(".katex-display")).toBeNull();
    expect(root.querySelector("annotation")?.textContent).toBe("x^2");
  });

  it.each(["$$x^2$$", String.raw`\[x^2\]`])("renders display math: %s", (input) => {
    expect(render(input).querySelector(".katex-display")).not.toBeNull();
    expect(render(`式：${input}です。`).querySelector(".katex-display")).not.toBeNull();
  });

  it.each(["$$", String.raw`\[`])("renders multiline equations: %s", (opening) => {
    const closing = opening === "$$" ? "$$" : String.raw`\]`;
    const root = render(`${opening}\n\\begin{aligned}\nx &= 1 \\\\\ny &= 2\n\\end{aligned}\n${closing}`);
    expect(root.querySelector(".katex-display .katex")).not.toBeNull();
    expect(root.querySelector(".katex-error")).toBeNull();
  });

  it("renders math inside lists and tables", () => {
    const root = render("- $x^2$\n\n| 式 |\n| --- |\n| \\(y^2\\) |");
    expect(root.querySelector("li .katex")).not.toBeNull();
    expect(root.querySelector("td .katex")).not.toBeNull();
  });

  it("leaves math inside code and escaped dollars literal", () => {
    const root = render("`$x$`\n\n```latex\n\\(x\\)\n$$x$$\n```\n\n\\$x\\$ and $5 and $10");
    expect(root.querySelector(".katex")).toBeNull();
    expect(root.querySelector("pre code")?.textContent).toBe("\\(x\\)\n$$x$$\n");
    expect(root.textContent).toContain("$x$ and $5 and $10");
  });

  it.each(["$x", "$$x", "$$x$", String.raw`\(x`, String.raw`\[x`])("retains incomplete streaming math: %s", (input) => {
    const root = render(input);
    expect(root.querySelector(".katex, .katex-error")).toBeNull();
    expect(root.textContent?.trim()).toBe(input);
  });

  it("keeps rendering after invalid math and refuses trusted HTML commands", () => {
    const root = render(String.raw`$\frac{<img src=x onerror=alert(1)>}$` + "\n\nAfter\n\n" + String.raw`$\href{javascript:alert(1)}{click}$`);
    expect(root.querySelector(".katex-error")).not.toBeNull();
    expect(root.textContent).toContain("After");
    expect(root.querySelector("img, a, script, [onerror]")).toBeNull();
  });
});
