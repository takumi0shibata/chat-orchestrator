import { ChangeEvent, FormEvent, MouseEvent, useEffect, useMemo, useRef, useState } from "react";
import {
  createConversation,
  deleteAllConversations,
  deleteConversation,
  extractAttachments,
  fetchConversationMessages,
  fetchConversations,
  fetchProviderModels,
  fetchProviders,
  fetchSkills,
  streamChat
} from "./api";
import type { ChatMessage, ConversationSummary, ModelInfo, ProviderInfo, SkillInfo } from "./types";

const ACTIVE_CONVERSATION_KEY = "chat_orchestrator_active_conversation_id";

type RichModel = ModelInfo & {
  providerId: string;
  providerLabel: string;
  providerEnabled: boolean;
};

type Attachment = {
  id: string;
  name: string;
  content: string;
};

type SkillChartPoint = {
  time: string;
  value: number;
  raw: string;
};

type SkillChartPayload = {
  schema: "boj_timeseries_chart/v1";
  series_label: string;
  frequency: string;
  points: SkillChartPoint[];
};

const BOJ_CHART_SCHEMA = "boj_timeseries_chart/v1";

function PlusIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

function TrashIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path
        d="M4 7h16M9 7V5h6v2m-8 0 1 12h8l1-12"
        stroke="currentColor"
        strokeWidth="2"
        fill="none"
        strokeLinecap="round"
      />
    </svg>
  );
}

function SendIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path
        d="M12 19V6M6.5 11.5 12 6l5.5 5.5"
        stroke="currentColor"
        strokeWidth="2"
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function StopIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <rect x="7" y="7" width="10" height="10" rx="2" fill="currentColor" />
    </svg>
  );
}

function ChevronDownIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="m6 9 6 6 6-6" stroke="currentColor" strokeWidth="2" fill="none" strokeLinecap="round" />
    </svg>
  );
}

function formatUpdatedAt(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function buildUserInput(text: string, attachments: Attachment[]): string {
  if (attachments.length === 0) return text;

  const files = attachments
    .map((file) => `- ${file.name}\n${file.content}`)
    .join("\n\n");

  return `${text}\n\n[Attached files]\n${files}`;
}

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

function markdownToHtml(markdown: string): string {
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

function isSkillChartPoint(node: unknown): node is SkillChartPoint {
  if (!node || typeof node !== "object") return false;
  const item = node as Record<string, unknown>;
  return (
    typeof item.time === "string" &&
    typeof item.value === "number" &&
    Number.isFinite(item.value) &&
    typeof item.raw === "string"
  );
}

function isSkillChartPayload(node: unknown): node is SkillChartPayload {
  if (!node || typeof node !== "object") return false;
  const item = node as Record<string, unknown>;
  return (
    item.schema === BOJ_CHART_SCHEMA &&
    typeof item.series_label === "string" &&
    typeof item.frequency === "string" &&
    Array.isArray(item.points) &&
    item.points.length > 0 &&
    item.points.every(isSkillChartPoint)
  );
}

function extractChartPayload(messageContent: string): { chart: SkillChartPayload | null; contentWithoutChartBlock: string } {
  let chart: SkillChartPayload | null = null;
  const contentWithoutChartBlock = messageContent.replace(/```chart-json\s*\n([\s\S]*?)```/g, (full, block) => {
    if (chart) return "";
    try {
      const parsed = JSON.parse(block) as unknown;
      if (!isSkillChartPayload(parsed)) return full;
      chart = parsed;
      return "";
    } catch {
      return full;
    }
  });
  return {
    chart,
    contentWithoutChartBlock: contentWithoutChartBlock.replace(/\n{3,}/g, "\n\n").trimEnd()
  };
}

function buildPolyline(points: SkillChartPoint[], width: number, height: number, padding: number): string {
  if (points.length === 0) return "";
  const innerWidth = width - padding * 2;
  const innerHeight = height - padding * 2;
  const values = points.map((item) => item.value);
  const minValue = Math.min(...values);
  const maxValue = Math.max(...values);
  const span = maxValue - minValue || Math.max(Math.abs(maxValue), 1) * 0.05;

  const coords = points.map((point, index) => {
    const x = points.length <= 1 ? width / 2 : padding + (innerWidth * index) / (points.length - 1);
    const ratio = (point.value - minValue) / span;
    const y = padding + innerHeight - ratio * innerHeight;
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  });
  return coords.join(" ");
}

function formatChartValue(value: number): string {
  if (Math.abs(value) >= 1000) return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
  if (Math.abs(value) >= 10) return value.toFixed(2);
  return value.toFixed(4);
}

function SkillChartCard({ chart }: { chart: SkillChartPayload }) {
  const width = 680;
  const height = 260;
  const padding = 28;
  const polyline = buildPolyline(chart.points, width, height, padding);
  const values = chart.points.map((item) => item.value);
  const minValue = Math.min(...values);
  const maxValue = Math.max(...values);
  const middlePoint = chart.points[Math.floor((chart.points.length - 1) / 2)];

  return (
    <section className="skill-chart-card">
      <div className="chart-label">
        <span>{chart.series_label}</span>
        <span>{chart.frequency === "D" ? "日次" : chart.frequency === "M" ? "月次" : chart.frequency}</span>
      </div>
      <svg className="skill-chart-svg" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${chart.series_label} 時系列`}>
        <line className="chart-axis" x1={padding} y1={padding} x2={padding} y2={height - padding} />
        <line className="chart-axis" x1={padding} y1={height - padding} x2={width - padding} y2={height - padding} />
        <polyline className="chart-line" points={polyline} />
        <text className="chart-y-label" x={padding + 6} y={padding + 12}>
          max {formatChartValue(maxValue)}
        </text>
        <text className="chart-y-label" x={padding + 6} y={height - padding - 6}>
          min {formatChartValue(minValue)}
        </text>
        <text className="chart-x-label" x={padding} y={height - 8}>
          {chart.points[0].time}
        </text>
        <text className="chart-x-label" x={width / 2} y={height - 8} textAnchor="middle">
          {middlePoint.time}
        </text>
        <text className="chart-x-label" x={width - padding} y={height - 8} textAnchor="end">
          {chart.points[chart.points.length - 1].time}
        </text>
      </svg>
    </section>
  );
}

export function App() {
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [models, setModels] = useState<RichModel[]>([]);

  const [modelKey, setModelKey] = useState<string>("");
  const [skillId, setSkillId] = useState<string>("");
  const [temperature, setTemperature] = useState<number | null>(0.3);
  const [reasoningEffort, setReasoningEffort] = useState<"low" | "medium" | "high" | null>(null);
  const [enableWebTool, setEnableWebTool] = useState<boolean>(false);

  const [conversationId, setConversationId] = useState<string>("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState<string>("");
  const [attachments, setAttachments] = useState<Attachment[]>([]);

  const [error, setError] = useState<string>("");
  const [loading, setLoading] = useState<boolean>(false);
  const [showThinking, setShowThinking] = useState<boolean>(false);
  const [showSkillRunning, setShowSkillRunning] = useState<boolean>(false);
  const [sidebarOpen, setSidebarOpen] = useState<boolean>(true);

  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  const selectedModel = useMemo(
    () => models.find((item) => `${item.providerId}::${item.id}` === modelKey),
    [models, modelKey]
  );
  const selectedSkill = useMemo(() => skills.find((item) => item.id === skillId), [skills, skillId]);
  const canUseWebTool = Boolean(
    selectedModel &&
      selectedModel.api_mode === "responses" &&
      (selectedModel.providerId === "openai" || selectedModel.providerId === "azure_openai")
  );

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, loading]);

  const resizeTextarea = () => {
    if (!textareaRef.current) return;
    textareaRef.current.style.height = "auto";
    textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 180)}px`;
  };

  const selectConversation = async (id: string, persist = true) => {
    const history = await fetchConversationMessages(id);
    setConversationId(id);
    setMessages(history);
    if (persist) localStorage.setItem(ACTIVE_CONVERSATION_KEY, id);
  };

  const loadConversations = async (targetConversationId?: string) => {
    const list = await fetchConversations();
    setConversations(list);

    const candidate =
      targetConversationId ||
      localStorage.getItem(ACTIVE_CONVERSATION_KEY) ||
      (list.length > 0 ? list[0].id : "");

    if (candidate) {
      await selectConversation(candidate, false);
      return;
    }

    const created = await createConversation();
    await loadConversations(created.id);
  };

  const loadModels = async (providers: ProviderInfo[]) => {
    const chunks = await Promise.all(
      providers.map(async (provider) => {
        const list = await fetchProviderModels(provider.id);
        return list.map(
          (model): RichModel => ({
            ...model,
            providerId: provider.id,
            providerLabel: provider.label,
            providerEnabled: provider.enabled
          })
        );
      })
    );

    const merged = chunks.flat();
    setModels(merged);

    const enabledProvider = providers.find((item) => item.enabled) || providers[0];
    const initial =
      merged.find((item) => item.providerId === enabledProvider?.id && item.id === enabledProvider.default_model) ||
      merged.find((item) => item.providerEnabled) ||
      merged[0];
    if (initial) {
      setModelKey(`${initial.providerId}::${initial.id}`);
      setTemperature(initial.supports_temperature ? (initial.default_temperature ?? 0.3) : null);
      setReasoningEffort(initial.supports_reasoning_effort ? initial.default_reasoning_effort : null);
    }
  };

  useEffect(() => {
    const load = async () => {
      try {
        const [providerList, skillList] = await Promise.all([fetchProviders(), fetchSkills()]);
        setSkills(skillList);
        await loadModels(providerList);
        await loadConversations();
      } catch (e) {
        setError(e instanceof Error ? e.message : "初期化に失敗しました");
      }
    };
    void load();
  }, []);

  const onModelChange = (value: string) => {
    setModelKey(value);
    const item = models.find((entry) => `${entry.providerId}::${entry.id}` === value);
    if (!item) return;

    if (!item.supports_temperature) setTemperature(null);
    else if (temperature === null) setTemperature(item.default_temperature ?? 0.3);

    if (!item.supports_reasoning_effort) setReasoningEffort(null);
    else if (!reasoningEffort) setReasoningEffort(item.default_reasoning_effort ?? "medium");

    if (!(item.api_mode === "responses" && (item.providerId === "openai" || item.providerId === "azure_openai"))) {
      setEnableWebTool(false);
    }
  };

  useEffect(() => {
    if (!canUseWebTool && enableWebTool) setEnableWebTool(false);
  }, [canUseWebTool, enableWebTool]);

  const onNewChat = async () => {
    try {
      const created = await createConversation();
      await loadConversations(created.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "新規チャットの作成に失敗しました");
    }
  };

  const onDeleteConversation = async (id: string) => {
    if (!window.confirm("この会話を削除しますか？")) return;

    try {
      await deleteConversation(id);
      const list = await fetchConversations();
      setConversations(list);

      if (conversationId === id) {
        if (list.length > 0) await selectConversation(list[0].id);
        else {
          const created = await createConversation();
          await loadConversations(created.id);
        }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "会話の削除に失敗しました");
    }
  };

  const onDeleteAllConversations = async () => {
    if (!window.confirm("全ての会話履歴を削除しますか？この操作は元に戻せません。")) return;

    try {
      await deleteAllConversations();
      const created = await createConversation();
      await loadConversations(created.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "履歴の全削除に失敗しました");
    }
  };

  const onAttachFiles = async (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files || []);
    if (files.length === 0) return;

    try {
      const extracted = await extractAttachments(files);
      const next = extracted.map((file) => ({
        id: `${file.name}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
        name: file.name,
        content: file.content
      }));
      setAttachments((prev) => [...prev, ...next]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "ファイルの読み込みに失敗しました");
    } finally {
      if (event.target) event.target.value = "";
    }
  };

  const onRemoveAttachment = (id: string) => {
    setAttachments((prev) => prev.filter((item) => item.id !== id));
  };

  const onMarkdownClick = async (event: MouseEvent<HTMLDivElement>) => {
    const target = event.target as HTMLElement;
    const button = target.closest<HTMLButtonElement>("[data-copy-btn='1']");
    if (!button) return;

    const wrap = button.closest(".code-wrap");
    const code = wrap?.querySelector("pre code");
    const text = code?.textContent || "";
    if (!text) return;

    try {
      await navigator.clipboard.writeText(text);
      const prev = button.textContent;
      button.textContent = "Copied";
      window.setTimeout(() => {
        button.textContent = prev || "Copy";
      }, 1200);
    } catch {
      button.textContent = "Failed";
      window.setTimeout(() => {
        button.textContent = "Copy";
      }, 1200);
    }
  };

  const onCancelStreaming = () => {
    abortControllerRef.current?.abort();
  };

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    const trimmed = input.trim();
    if ((!trimmed && attachments.length === 0) || !selectedModel || !conversationId || loading) return;

    if (!selectedModel.providerEnabled) {
      setError(`${selectedModel.providerLabel} のAPIキーが設定されていません`);
      return;
    }

    setLoading(true);
    setError("");
    setShowThinking(Boolean(selectedModel.supports_reasoning_effort));
    setShowSkillRunning(Boolean(skillId));

    const userRaw = trimmed || "[Attached files only]";
    const payloadText = buildUserInput(userRaw, attachments);

    setInput("");
    setAttachments([]);
    if (textareaRef.current) textareaRef.current.style.height = "auto";

    const userMessage: ChatMessage = { role: "user", content: userRaw };
    const assistantPlaceholder: ChatMessage = { role: "assistant", content: "" };
    setMessages((prev) => [...prev, userMessage, assistantPlaceholder]);
    const abortController = new AbortController();
    abortControllerRef.current = abortController;

    try {
      const done = await streamChat({
        providerId: selectedModel.providerId,
        model: selectedModel.id,
        userInput: payloadText,
        conversationId,
        skillId: skillId || undefined,
        temperature,
        reasoningEffort,
        enableWebTool: canUseWebTool ? enableWebTool : false,
        signal: abortController.signal,
        onChunk: (delta) => {
          if (delta) setShowThinking(false);
          if (delta) setShowSkillRunning(false);
          setMessages((prev) => {
            const next = [...prev];
            const lastIndex = next.length - 1;
            if (lastIndex >= 0 && next[lastIndex].role === "assistant") {
              next[lastIndex] = { ...next[lastIndex], content: `${next[lastIndex].content}${delta}` };
            }
            return next;
          });
        },
        onSkillStatus: (status) => {
          setShowSkillRunning(status === "running");
        }
      });

      const skillOutput = done.skill_output;
      if (skillOutput) {
        setMessages((prev) => {
          const next = [...prev];
          const lastIndex = next.length - 1;
          if (lastIndex >= 0 && next[lastIndex].role === "assistant") {
            if (skillId === "boj_timeseries_insight") {
              const parsed = extractChartPayload(skillOutput);
              if (parsed.chart) {
                next[lastIndex] = {
                  ...next[lastIndex],
                  content: `${next[lastIndex].content}\n\n\`\`\`chart-json\n${JSON.stringify(parsed.chart)}\n\`\`\``
                };
              }
            }
            // Default behavior: do not render raw skill output in chat UI.
            // Exception skills can enrich message content above (e.g., chart block injection).
          }
          return next;
        });
      }

      const latestConversations = await fetchConversations();
      setConversations(latestConversations);
    } catch (e) {
      const isAbortError = e instanceof Error && e.name === "AbortError";
      if (isAbortError) {
        setMessages((prev) => {
          const next = [...prev];
          const lastIndex = next.length - 1;
          if (lastIndex >= 0 && next[lastIndex].role === "assistant" && !next[lastIndex].content.trim()) {
            next[lastIndex] = { ...next[lastIndex], content: "[キャンセルしました]" };
          }
          return next;
        });
      } else {
        setError(e instanceof Error ? e.message : "送信に失敗しました");
        setMessages((prev) => prev.slice(0, -2));
      }
    } finally {
      abortControllerRef.current = null;
      setShowSkillRunning(false);
      setShowThinking(false);
      setLoading(false);
    }
  };

  return (
    <div className={`app-shell ${sidebarOpen ? "" : "sidebar-collapsed"}`}>
      <aside className={`sidebar ${sidebarOpen ? "" : "closed"}`}>
        <div className="sidebar-header">
          <h1>Orchestrator</h1>
          <div className="sidebar-actions">
            <button className="icon-btn" type="button" onClick={onNewChat} title="New chat">
              <PlusIcon />
            </button>
            <button className="icon-btn danger" type="button" onClick={onDeleteAllConversations} title="Clear all">
              <TrashIcon />
            </button>
          </div>
        </div>

        <div className="session-list">
          {conversations.map((session) => (
            <div key={session.id} className={`session-item ${session.id === conversationId ? "active" : ""}`}>
              <button
                className="session-main"
                type="button"
                onClick={() => {
                  void selectConversation(session.id);
                }}
              >
                <span className="session-title">{session.title}</span>
                <span className="session-meta">
                  {session.message_count} msgs • {formatUpdatedAt(session.updated_at)}
                </span>
              </button>
              <button
                className="session-delete"
                type="button"
                title="Delete conversation"
                onClick={() => {
                  void onDeleteConversation(session.id);
                }}
              >
                <TrashIcon />
              </button>
            </div>
          ))}
        </div>
      </aside>

      <main className="chat-main">
        <button
          className="sidebar-toggle"
          type="button"
          onClick={() => setSidebarOpen((prev) => !prev)}
          title={sidebarOpen ? "Hide history" : "Show history"}
        >
          {sidebarOpen ? "<" : ">"}
        </button>

        <section className="messages">
          {messages.map((message, index) => {
            const chartResult = message.role === "assistant" ? extractChartPayload(message.content) : null;
            const renderedContent = chartResult?.contentWithoutChartBlock ?? message.content;
            return (
              <article className={`bubble ${message.role}`} key={`${message.role}-${index}`}>
                {message.role === "assistant" && loading && showSkillRunning && index === messages.length - 1 ? (
                  <div className="thinking">
                    <span>{selectedSkill?.name || "Skill"} running</span>
                    <span className="dots">
                      <i />
                      <i />
                      <i />
                    </span>
                  </div>
                ) : message.role === "assistant" && loading && showThinking && index === messages.length - 1 ? (
                  <div className="thinking">
                    <span>Thinking</span>
                    <span className="dots">
                      <i />
                      <i />
                      <i />
                    </span>
                  </div>
                ) : message.role === "assistant" ? (
                  <>
                    <div
                      className="markdown"
                      onClick={onMarkdownClick}
                      dangerouslySetInnerHTML={{ __html: markdownToHtml(renderedContent) }}
                    />
                    {chartResult?.chart && <SkillChartCard chart={chartResult.chart} />}
                  </>
                ) : (
                  <p>{message.content}</p>
                )}
              </article>
            );
          })}
          <div ref={messagesEndRef} />
        </section>

        <form className="composer" onSubmit={onSubmit}>
          {attachments.length > 0 && (
            <div className="attachment-row">
              {attachments.map((file) => (
                <span className="attachment-chip" key={file.id}>
                  {file.name}
                  <button type="button" onClick={() => onRemoveAttachment(file.id)}>
                    x
                  </button>
                </span>
              ))}
            </div>
          )}

          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => {
              setInput(e.target.value);
              resizeTextarea();
            }}
            onKeyDown={(e) => {
              if (e.metaKey && e.key === "Enter") {
                e.preventDefault();
                e.currentTarget.form?.requestSubmit();
              }
            }}
            rows={2}
            placeholder="Message Orchestrator..."
          />

          <div className="composer-tools">
            <button
              className="icon-btn"
              type="button"
              title="Attach files"
              onClick={() => fileInputRef.current?.click()}
            >
              <PlusIcon />
            </button>
            <input ref={fileInputRef} type="file" multiple className="hidden-file" onChange={onAttachFiles} />

            <div className="select-wrap">
              <select value={modelKey} onChange={(e) => onModelChange(e.target.value)} title="Model">
                {models.map((item) => (
                  <option value={`${item.providerId}::${item.id}`} key={`${item.providerId}:${item.id}`}>
                    {item.label} ({item.providerLabel})
                  </option>
                ))}
              </select>
              <ChevronDownIcon />
            </div>

            <div className="select-wrap">
              <select value={skillId} onChange={(e) => setSkillId(e.target.value)} title="Skill">
                <option value="">No skill</option>
                {skills.map((skill) => (
                  <option value={skill.id} key={skill.id}>
                    {skill.name}
                  </option>
                ))}
              </select>
              <ChevronDownIcon />
            </div>

            {selectedModel?.supports_temperature && (
              <input
                className="mini-input"
                type="number"
                value={temperature ?? 0.3}
                step={0.1}
                min={0}
                max={2}
                onChange={(e) => setTemperature(Number(e.target.value))}
                title="Temperature"
              />
            )}

            {selectedModel?.supports_reasoning_effort && (
              <div className="select-wrap">
                <select
                  value={reasoningEffort ?? "medium"}
                  onChange={(e) => setReasoningEffort(e.target.value as "low" | "medium" | "high")}
                  title="Reasoning"
                >
                  <option value="low">Low</option>
                  <option value="medium">Medium</option>
                  <option value="high">High</option>
                </select>
                <ChevronDownIcon />
              </div>
            )}

            {canUseWebTool && (
              <label className="web-tool-toggle" title="Enable web search tool">
                <input
                  type="checkbox"
                  checked={enableWebTool}
                  onChange={(e) => setEnableWebTool(e.target.checked)}
                />
                <span>Web</span>
              </label>
            )}

            {loading ? (
              <button className="send-btn stop-btn" type="button" onClick={onCancelStreaming} title="Cancel generation">
                <StopIcon />
              </button>
            ) : (
              <button className="send-btn" type="submit" disabled={!conversationId || !selectedModel}>
                <SendIcon />
              </button>
            )}
          </div>
        </form>

        {error && <p className="error">{error}</p>}
      </main>
    </div>
  );
}
