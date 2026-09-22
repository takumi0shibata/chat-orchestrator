import { MouseEvent } from "react";

import { markdownToHtml } from "../lib/markdown";

export function MarkdownContent({ content, conversationId }: { content: string; conversationId?: string }) {
  const onClick = async (event: MouseEvent<HTMLDivElement>) => {
    const target = event.target as HTMLElement;
    const button = target.closest<HTMLButtonElement>("[data-copy-btn='1']");
    if (!button) return;

    const wrap = button.closest(".code-wrap");
    const code = wrap?.querySelector("pre code");
    const text = code?.textContent || "";
    if (!text) return;
    const feedback = button.querySelector<HTMLElement>(".copy-feedback");

    const reset = () => {
      button.dataset.state = "idle";
      button.setAttribute("aria-label", "Copy code");
      button.setAttribute("title", "Copy code");
      if (feedback) feedback.textContent = "";
    };

    try {
      await navigator.clipboard.writeText(text);
      button.dataset.state = "copied";
      button.setAttribute("aria-label", "Code copied");
      button.setAttribute("title", "Copied");
      if (feedback) feedback.textContent = "Code copied";
      window.setTimeout(reset, 1200);
    } catch {
      button.dataset.state = "failed";
      button.setAttribute("aria-label", "Copy failed");
      button.setAttribute("title", "Copy failed");
      if (feedback) feedback.textContent = "Copy failed";
      window.setTimeout(reset, 1200);
    }
  };

  return <div className="markdown" onClick={onClick} dangerouslySetInnerHTML={{ __html: markdownToHtml(content, conversationId) }} />;
}
