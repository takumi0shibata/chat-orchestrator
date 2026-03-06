function escapeHtml(input: string): string {
  return input
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function formatInline(text: string): string {
  let out = text;
  out = out.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>');
  out = out.replace(/`([^`]+)`/g, "<code>$1</code>");
  out = out.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  out = out.replace(/\*([^*]+)\*/g, "<em>$1</em>");
  return out;
}

function highlightEscapedCode(language: string, escapedCode: string): string {
  let code = escapedCode;
  const tokens: string[] = [];

  const stash = (pattern: RegExp, cls: string) => {
    code = code.replace(pattern, (match) => {
      const key = `@@TOK${tokens.length}@@`;
      tokens.push(`<span class="tok ${cls}">${match}</span>`);
      return key;
    });
  };

  const restore = () => {
    code = code.replace(/@@TOK(\d+)@@/g, (_, idx) => tokens[Number(idx)] || "");
  };

  const lang = language.toLowerCase();
  const isPython = lang === "python" || lang === "py";
  const isJsLike = ["javascript", "js", "typescript", "ts", "tsx", "jsx"].includes(lang);
  const isJson = lang === "json";
  const isShell = ["bash", "sh", "zsh", "shell"].includes(lang);

  stash(/#.*$/gm, "comment");
  stash(/\/\/.*$/gm, "comment");
  stash(/\/\*[\s\S]*?\*\//g, "comment");
  stash(/("""[\s\S]*?"""|'''[\s\S]*?'''|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')/g, "string");

  if (isPython) {
    stash(/\b(def|class|if|elif|else|for|while|try|except|finally|return|import|from|as|pass|break|continue|with|lambda|yield|True|False|None|and|or|not|in|is|async|await)\b/g, "kw");
    stash(/(^|\s)(@\w+)/gm, "decorator");
  } else if (isJsLike) {
    stash(/\b(function|class|const|let|var|if|else|for|while|switch|case|break|continue|return|try|catch|finally|throw|import|from|export|default|new|async|await|true|false|null|undefined)\b/g, "kw");
  } else if (isJson) {
    stash(/"([^"\\]|\\.)*"\s*(?=:)/g, "property");
    stash(/\b(true|false|null)\b/g, "kw");
  } else if (isShell) {
    stash(/(^|\s)(sudo|cd|ls|cat|grep|awk|sed|find|curl|wget|npm|pnpm|yarn|python|pip|uv|git|docker|kubectl)\b/gm, "kw");
  }

  stash(/\b\d+(\.\d+)?\b/g, "num");
  restore();
  return code;
}

function renderCodeBlock(rawChunk: string): string {
  const firstBreak = rawChunk.indexOf("\n");
  const langToken = firstBreak >= 0 ? rawChunk.slice(0, firstBreak).trim() : "";
  const hasLang = /^[a-zA-Z0-9_+-]{1,20}$/.test(langToken);
  const language = hasLang ? langToken : "plain";
  const body = hasLang ? rawChunk.slice(firstBreak + 1) : rawChunk;
  const escapedBody = escapeHtml(body);
  const highlighted = highlightEscapedCode(language, escapedBody);
  return `<div class="code-wrap"><button class="code-copy-btn" data-copy-btn="1" type="button">Copy</button><pre class="code-block language-${language}"><code>${highlighted}</code></pre></div>`;
}

function isTableSeparatorLine(line: string): boolean {
  const trimmed = line.trim();
  if (!trimmed || !trimmed.includes("|")) return false;

  const normalized = trimmed.replace(/^\|/, "").replace(/\|$/, "");
  const cells = normalized.split("|").map((cell) => cell.trim());
  if (cells.length === 0) return false;

  return cells.every((cell) => /^:?-{3,}:?$/.test(cell));
}

function splitTableRow(line: string): string[] {
  const normalized = line.trim().replace(/^\|/, "").replace(/\|$/, "");
  return normalized.split("|").map((cell) => formatInline(cell.trim()));
}

function renderTable(header: string[], rows: string[][]): string {
  const thead = `<thead><tr>${header.map((cell) => `<th>${cell}</th>`).join("")}</tr></thead>`;
  const tbodyRows = rows
    .map((row) => `<tr>${header.map((_, idx) => `<td>${row[idx] || ""}</td>`).join("")}</tr>`)
    .join("");
  return `<table>${thead}<tbody>${tbodyRows}</tbody></table>`;
}

export function markdownToHtml(markdown: string): string {
  const chunks = markdown.split(/```/);
  const htmlParts: string[] = [];

  for (let i = 0; i < chunks.length; i += 1) {
    const chunk = chunks[i];
    if (i % 2 === 1) {
      htmlParts.push(renderCodeBlock(chunk));
      continue;
    }

    const lines = escapeHtml(chunk).split("\n");
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

      if (line.startsWith("- ") || line.startsWith("* ")) {
        if (!inList) {
          htmlParts.push("<ul>");
          inList = true;
        }
        htmlParts.push(`<li>${formatInline(line.slice(2))}</li>`);
        lineIndex += 1;
        continue;
      }

      if (inList) {
        htmlParts.push("</ul>");
        inList = false;
      }

      const nextLine = lines[lineIndex + 1]?.trim() || "";
      if (line.includes("|") && isTableSeparatorLine(nextLine)) {
        const header = splitTableRow(line);
        const rows: string[][] = [];
        lineIndex += 2;

        while (lineIndex < lines.length) {
          const rowLine = lines[lineIndex].trim();
          if (!rowLine || !rowLine.includes("|")) break;
          rows.push(splitTableRow(rowLine));
          lineIndex += 1;
        }

        htmlParts.push(renderTable(header, rows));
        continue;
      }

      if (line.startsWith("### ")) {
        htmlParts.push(`<h3>${formatInline(line.slice(4))}</h3>`);
      } else if (line.startsWith("## ")) {
        htmlParts.push(`<h2>${formatInline(line.slice(3))}</h2>`);
      } else if (line.startsWith("# ")) {
        htmlParts.push(`<h1>${formatInline(line.slice(2))}</h1>`);
      } else {
        htmlParts.push(`<p>${formatInline(line)}</p>`);
      }
      lineIndex += 1;
    }

    if (inList) htmlParts.push("</ul>");
  }

  return htmlParts.join("");
}
