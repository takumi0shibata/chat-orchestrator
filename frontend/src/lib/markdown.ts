import hljs from "highlight.js/lib/common";
import katex from "katex";
import MarkdownIt from "markdown-it";
import texmath from "markdown-it-texmath";

export function artifactDownloadUrl(url: string, conversationId?: string): string | null {
  if (!conversationId) return null;
  const prefix = /^(?:sandbox:\/workspace\/|file:\/\/\/workspace\/|\/workspace\/)/i.exec(url);
  const relative = prefix ? url.slice(prefix[0].length) : url;
  // Query strings and fragments are not filesystem paths. Encode literal ?/# in filenames.
  if (/[?#]/.test(relative)) return null;
  let path: string;
  try { path = decodeURIComponent(relative); }
  catch { return null; }
  if (path.startsWith("./")) path = path.slice(2);
  if (!path || path.startsWith("/") || /^[a-z][a-z0-9+.-]*:/i.test(path)
    || /[\\\x00-\x1f\x7f]/.test(path)
    || path.split("/").some((part) => !part || part === ".." || part === ".")) return null;
  return `/api/conversations/${encodeURIComponent(conversationId)}/download?path=${encodeURIComponent(path)}`;
}

function escapeHtmlText(input: string): string {
  return input.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
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

const markdown = new MarkdownIt({ html: false, breaks: true });
const normalizeLink = markdown.normalizeLink.bind(markdown);
const isExternalLink = (url: string) => /^https?:\/\//i.test(url);

// Keep artifact URLs unnormalized until validation: URI normalization would hide
// malformed percent escapes and could change the file's actual name.
markdown.normalizeLink = (url) => isExternalLink(url) ? normalizeLink(url) : url;
markdown.validateLink = (url) => isExternalLink(url) || artifactDownloadUrl(url, "validation") !== null;
markdown.renderer.rules.fence = (tokens, index) => renderCodeBlock(tokens[index].info.trim(), tokens[index].content);
markdown.renderer.rules.code_block = (tokens, index) => renderCodeBlock("", tokens[index].content);
markdown.core.ruler.after("inline", "artifact_links", (state) => {
  const conversationId = typeof state.env.conversationId === "string" ? state.env.conversationId : undefined;
  for (const token of state.tokens) {
    const children = token.children || [];
    let inertLink = false;
    for (const child of children) {
      if (child.type === "link_open") {
        const url = String(child.attrGet("href") || "");
        inertLink = false;
        if (isExternalLink(url)) {
          child.attrSet("target", "_blank");
          child.attrSet("rel", "noreferrer");
        } else {
          const href = artifactDownloadUrl(url, conversationId);
          if (href) {
            child.attrSet("href", href);
            child.attrSet("download", "");
          } else {
            child.type = "text";
            child.content = "";
            inertLink = true;
          }
        }
      } else if (child.type === "link_close" && inertLink) {
        child.type = "text";
        child.content = "";
        inertLink = false;
      }
    }
  }
});
// Images are not file-download links; do not load local paths as browser URLs.
const renderImage = markdown.renderer.rules.image;
markdown.renderer.rules.image = (tokens, index, options, env, renderer) => {
  const src = String(tokens[index].attrGet("src") || "");
  return isExternalLink(src) ? renderImage(tokens, index, options, env, renderer)
    : escapeHtmlText(tokens[index].content);
};
markdown.use(texmath, {
  engine: katex,
  delimiters: ["dollars", "brackets"],
  katexOptions: { trust: false, throwOnError: false, maxExpand: 1000, maxSize: 100 },
});
// Build the wrapper directly, rather than interpolating KaTeX HTML through
// String.replace (whose replacement syntax treats dollar signs specially).
for (const name of ["math_inline", "math_inline_double", "math_block", "math_block_eqno"]) {
  markdown.renderer.rules[name] = (tokens, index) => {
    const token = tokens[index];
    const displayMode = name !== "math_inline";
    let html: string;
    try {
      html = katex.renderToString(token.content, {
        displayMode, trust: false, throwOnError: false, maxExpand: 1000, maxSize: 100,
      });
    } catch {
      html = escapeHtmlText(token.content);
    }
    if (!displayMode) return `<eq>${html}</eq>`;
    const number = name === "math_block_eqno" ? `<span>(${escapeHtmlText(token.info)})</span>` : "";
    return `<section${number ? ' class="eqno"' : ""}><eqn>${html}</eqn>${number}</section>`;
  };
}
markdown.inline.ruler.before("math_inline_double", "incomplete_display_math", (state, silent) => {
  if (!state.src.startsWith("$$", state.pos)) return false;
  const end = state.src.indexOf("$$", state.pos + 2);
  if (end >= 0 && end < state.posMax) return false;
  if (!silent) state.pending += state.src.slice(state.pos, state.posMax);
  state.pos = state.posMax;
  return true;
});
// texmath handles bracket display math at the beginning of a block. Also allow
// it in a paragraph, and retain unfinished bracket delimiters during streaming.
markdown.inline.ruler.before("escape", "bracket_display_and_incomplete", (state, silent) => {
  const opening = state.src.slice(state.pos, state.pos + 2);
  if (opening !== "\\[" && opening !== "\\(") return false;
  const closing = opening === "\\[" ? "\\]" : "\\)";
  const end = state.src.indexOf(closing, state.pos + 2);
  if (opening === "\\[" && end >= 0 && end < state.posMax) {
    if (!silent) {
      const token = state.push("math_inline_double", "math", 0);
      token.content = state.src.slice(state.pos + 2, end);
    }
    state.pos = end + 2;
    return true;
  }
  if (end < 0 || end >= state.posMax) {
    if (!silent) state.pending += opening;
    state.pos += 2;
    return true;
  }
  return false;
});

export function markdownToHtml(content: string, conversationId?: string): string {
  return markdown.render(content, { conversationId });
}
