import hljs from "highlight.js/lib/common";

export function artifactDownloadUrl(url: string, conversationId?: string): string | null {
  if (!conversationId || !url.startsWith("sandbox:/workspace/")) return null;
  let path: string;
  try { path = decodeURIComponent(url.slice("sandbox:/workspace/".length)); }
  catch { return null; }
  if (!path || path.startsWith("/") || /[\\\x00-\x1f\x7f]/.test(path) || path.split("/").some((part) => part === ".." || part === ".")) return null;
  return `/api/conversations/${encodeURIComponent(conversationId)}/download?path=${encodeURIComponent(path)}`;
}

function escapeHtmlText(input: string): string {
  return input
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function escapeHtmlAttribute(input: string): string {
  return escapeHtmlText(input).replace(/'/g, "&#39;");
}

function formatInline(text: string, conversationId?: string): string {
  let out = text;
  const tokens: string[] = [];
  let markerPrefix = "\uE000";
  while (text.includes(markerPrefix)) markerPrefix += "\uE001";
  const markerSuffix = "\uE002";
  const markerPattern = new RegExp(`${markerPrefix}(\\d+)${markerSuffix}`, "g");

  const stash = (pattern: RegExp, render: (...args: string[]) => string) => {
    out = out.replace(pattern, (...args) => {
      const matchArgs = args.slice(0, -2) as string[];
      const key = `${markerPrefix}${tokens.length}${markerSuffix}`;
      tokens.push(render(...matchArgs));
      return key;
    });
  };

  stash(/\[([^\]]+)\]\((https?:\/\/[^\s)]+|sandbox:[^)]+)\)/g, (match, label, url) => {
    if (url.startsWith("sandbox:")) {
      const href = artifactDownloadUrl(url, conversationId);
      return href ? `<a href="${escapeHtmlAttribute(href)}" download>${escapeHtmlText(label)}</a>` : escapeHtmlText(match);
    }
    return `<a href="${escapeHtmlAttribute(url)}" target="_blank" rel="noreferrer">${escapeHtmlText(label)}</a>`;
  });
  stash(/`([^`]+)`/g, (_match, code) => `<code>${escapeHtmlText(code)}</code>`);
  stash(/\*\*([^*]+)\*\*/g, (_match, strong) => `<strong>${escapeHtmlText(strong)}</strong>`);
  stash(/\*([^*]+)\*/g, (_match, emphasis) => `<em>${escapeHtmlText(emphasis)}</em>`);

  out = escapeHtmlText(out);
  const resolvedTokens: string[] = [];
  const resolveToken = (index: number): string => {
    if (resolvedTokens[index] !== undefined) return resolvedTokens[index];
    const resolved = (tokens[index] || "").replace(markerPattern, (_, idx) => resolveToken(Number(idx)));
    resolvedTokens[index] = resolved;
    return resolved;
  };
  return out.replace(markerPattern, (_, idx) => resolveToken(Number(idx)));
}

function highlightCode(language: string, code: string): string {
  if (!hljs.getLanguage(language)) return escapeHtmlText(code);

  try {
    return hljs.highlight(code, { language, ignoreIllegals: true }).value;
  } catch {
    return escapeHtmlText(code);
  }
}

function renderCodeBlock(langToken: string, body: string): string {
  const hasLang = /^[a-zA-Z0-9_+-]{1,20}$/.test(langToken);
  const language = hasLang ? langToken : "plain";
  const highlighted = hasLang ? highlightCode(language, body) : escapeHtmlText(body);
  const languageLabel = hasLang
    ? `<span class="code-language">${escapeHtmlText(langToken)}</span>`
    : "<span></span>";
  return `<div class="code-wrap"><div class="code-toolbar">${languageLabel}<button class="code-copy-btn" data-copy-btn="1" data-state="idle" type="button" aria-label="Copy code" title="Copy code"><svg class="copy-icon" aria-hidden="true" viewBox="0 0 24 24"><rect x="9" y="9" width="11" height="11" rx="2"></rect><path d="M15 9V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h3"></path></svg><svg class="copy-check" aria-hidden="true" viewBox="0 0 24 24"><path d="m5 12 4 4L19 6"></path></svg><span class="sr-only copy-feedback" aria-live="polite"></span></button></div><pre class="code-block language-${language}"><code class="hljs">${highlighted}</code></pre></div>`;
}

type MarkdownSegment =
  | { kind: "prose"; content: string }
  | { kind: "code"; content: string; language: string };

function splitFencedBlocks(markdown: string): MarkdownSegment[] {
  const lines = markdown.match(/[^\n]*(?:\n|$)/g)?.filter(Boolean) || [];
  const segments: MarkdownSegment[] = [];
  let prose = "";
  let index = 0;

  const withoutLineEnding = (line: string) => line.replace(/\r?\n$/, "");

  while (index < lines.length) {
    const line = withoutLineEnding(lines[index]);
    const opening = line.match(/^ {0,3}(`{3,}|~{3,})([^\r\n]*)$/);
    const marker = opening?.[1] || "";
    const info = opening?.[2] || "";
    const invalidBacktickInfo = marker.startsWith("`") && info.includes("`");

    if (!opening || invalidBacktickInfo) {
      prose += lines[index];
      index += 1;
      continue;
    }

    if (prose) {
      segments.push({ kind: "prose", content: prose });
      prose = "";
    }

    index += 1;
    let code = "";
    while (index < lines.length) {
      const candidate = withoutLineEnding(lines[index]);
      const closing = candidate.match(/^ {0,3}(`+|~+)[ \t]*$/)?.[1];
      if (closing?.[0] === marker[0] && closing.length >= marker.length) {
        index += 1;
        break;
      }
      code += lines[index];
      index += 1;
    }

    const language = info.trim();
    segments.push({ kind: "code", content: code, language });
  }

  if (prose) segments.push({ kind: "prose", content: prose });
  return segments;
}

function isTableSeparatorLine(line: string): boolean {
  const trimmed = line.trim();
  if (!trimmed || !trimmed.includes("|")) return false;

  const normalized = trimmed.replace(/^\|/, "").replace(/\|$/, "");
  const cells = normalized.split("|").map((cell) => cell.trim());
  if (cells.length === 0) return false;

  return cells.every((cell) => /^:?-{3,}:?$/.test(cell));
}

function isThematicBreak(line: string): boolean {
  return /^(?:(?:\*[ \t]*){3,}|(?:-[ \t]*){3,}|(?:_[ \t]*){3,})$/.test(line);
}

function splitTableRow(line: string, conversationId?: string): string[] {
  const normalized = line.trim().replace(/^\|/, "").replace(/\|$/, "");
  return normalized.split("|").map((cell) => formatInline(cell.trim(), conversationId));
}

function renderTable(header: string[], rows: string[][]): string {
  const thead = `<thead><tr>${header.map((cell) => `<th>${cell}</th>`).join("")}</tr></thead>`;
  const tbodyRows = rows
    .map((row) => `<tr>${header.map((_, idx) => `<td>${row[idx] || ""}</td>`).join("")}</tr>`)
    .join("");
  return `<table>${thead}<tbody>${tbodyRows}</tbody></table>`;
}

export function markdownToHtml(markdown: string, conversationId?: string): string {
  const htmlParts: string[] = [];

  for (const segment of splitFencedBlocks(markdown)) {
    if (segment.kind === "code") {
      htmlParts.push(renderCodeBlock(segment.language, segment.content));
      continue;
    }

    const chunk = segment.content;
    const lines = chunk.split("\n");
    let inList = false;

    let lineIndex = 0;
    while (lineIndex < lines.length) {
      const line = lines[lineIndex].trim();
      if (!line) {
        if (inList) {
          htmlParts.push("</ul>");
          inList = false;
        }
        lineIndex += 1;
        continue;
      }

      if (isThematicBreak(line)) {
        if (inList) {
          htmlParts.push("</ul>");
          inList = false;
        }
        htmlParts.push("<hr>");
        lineIndex += 1;
        continue;
      }

      if (line.startsWith("- ") || line.startsWith("* ")) {
        if (!inList) {
          htmlParts.push("<ul>");
          inList = true;
        }
        htmlParts.push(`<li>${formatInline(line.slice(2), conversationId)}</li>`);
        lineIndex += 1;
        continue;
      }

      if (inList) {
        htmlParts.push("</ul>");
        inList = false;
      }

      const nextLine = lines[lineIndex + 1]?.trim() || "";
      if (line.includes("|") && isTableSeparatorLine(nextLine)) {
        const header = splitTableRow(line, conversationId);
        const rows: string[][] = [];
        lineIndex += 2;

        while (lineIndex < lines.length) {
          const rowLine = lines[lineIndex].trim();
          if (!rowLine || !rowLine.includes("|")) break;
          rows.push(splitTableRow(rowLine, conversationId));
          lineIndex += 1;
        }

        htmlParts.push(renderTable(header, rows));
        continue;
      }

      if (line.startsWith("### ")) {
        htmlParts.push(`<h3>${formatInline(line.slice(4), conversationId)}</h3>`);
      } else if (line.startsWith("## ")) {
        htmlParts.push(`<h2>${formatInline(line.slice(3), conversationId)}</h2>`);
      } else if (line.startsWith("# ")) {
        htmlParts.push(`<h1>${formatInline(line.slice(2), conversationId)}</h1>`);
      } else {
        htmlParts.push(`<p>${formatInline(line, conversationId)}</p>`);
      }
      lineIndex += 1;
    }

    if (inList) htmlParts.push("</ul>");
  }

  return htmlParts.join("");
}
