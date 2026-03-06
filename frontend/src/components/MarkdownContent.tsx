import { MouseEvent } from "react";

import { markdownToHtml } from "../lib/markdown";

export function MarkdownContent({ content }: { content: string }) {
  const onClick = async (event: MouseEvent<HTMLDivElement>) => {
    const target = event.target as HTMLElement;
    const button = target.closest<HTMLButtonElement>("[data-copy-btn='1']");
    if (!button) return;

    const wrap = button.closest(".code-wrap");
    const code = wrap?.querySelector("pre code");
    const text = code?.textContent || "";
    if (!text) return;

    try {
      await navigator.clipboard.writeText(text);
      const previous = button.textContent;
      button.textContent = "Copied";
      window.setTimeout(() => {
        button.textContent = previous || "Copy";
      }, 1200);
    } catch {
      button.textContent = "Failed";
      window.setTimeout(() => {
        button.textContent = "Copy";
      }, 1200);
    }
  };

  return <div className="markdown" onClick={onClick} dangerouslySetInnerHTML={{ __html: markdownToHtml(content) }} />;
}
