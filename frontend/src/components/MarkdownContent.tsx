import { MouseEvent, useState } from "react";

import { markdownToHtml } from "../lib/markdown";

export function MarkdownContent({ content, conversationId }: { content: string; conversationId?: string }) {
  const [downloadError, setDownloadError] = useState("");
  const onClick = async (event: MouseEvent<HTMLDivElement>) => {
    const target = event.target as HTMLElement;
    const link = target.closest<HTMLAnchorElement>("a[download]");
    const href = link?.getAttribute("href") || "";
    if (conversationId && href.startsWith(`/api/conversations/${encodeURIComponent(conversationId)}/download?`)) {
      event.preventDefault();
      setDownloadError("");
      try {
        const response = await fetch(href);
        if (!response.ok) throw new Error("This file is unavailable. It may have been moved or deleted.");
        const url = URL.createObjectURL(await response.blob());
        const save = document.createElement("a");
        save.href = url;
        save.download = new URL(href, window.location.href).searchParams.get("path")?.split("/").pop() || "download";
        document.body.appendChild(save);
        save.click();
        save.remove();
        window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      } catch (error) {
        setDownloadError(error instanceof Error ? error.message : "Could not download this file. Please retry.");
      }
      return;
    }
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

  return <><div className="markdown" onClick={onClick} dangerouslySetInnerHTML={{ __html: markdownToHtml(content, conversationId) }} />{downloadError && <p role="alert" className="error">{downloadError}</p>}</>;
}
