import { DragEvent as ReactDragEvent, FormEvent, KeyboardEvent, Suspense, lazy, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import type { CSSProperties, ReactNode } from "react";
import {
  ArrowUp, Check, ChevronDown, ChevronRight, Copy, File, FileArchive, FileCode, FileImage,
  FileSpreadsheet, FileText, Folder, FolderOpen, Globe, Paperclip, PanelRight, Pin, Plus,
  Presentation, RefreshCw, Search, Settings, Sparkles, SquarePen, SquareTerminal, X,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { api, events } from "./api";
import { MarkdownContent } from "./components/MarkdownContent";
import {
  exactSkillMatch,
  findSkillMention,
  matchingSkills,
  replaceSkillMention,
  skillMentionName,
} from "./lib/skillMention";
import type { SkillMention } from "./lib/skillMention";
import {
  activityEntries, compactions, contextUsage, finalAnswerStart, messageBlocks, reasoningActive, reasoningBlocks, reasoningTitle,
  type Compaction, type ReasoningBlock,
} from "./lib/timeline";
import { terminal } from "./types";
import type {
  AgentEvent,
  AppSettings,
  Attachment,
  Config,
  Conversation,
  CostSummary,
  Model,
  Named,
  Run,
  WorkspaceFile,
} from "./types";

const LAST_PROJECT_KEY = "workspace-last-project";
const HostTerminalPanel = lazy(() => import("./components/HostTerminalPanel").then((module) => ({ default: module.HostTerminalPanel })));
const SIDEBAR_WIDTH_KEY = "workspace-sidebar-width";
const MIN_SIDEBAR_WIDTH = 200;
const MAX_SIDEBAR_WIDTH = 400;
const FILES_WIDTH_KEY = "workspace-files-width";
const TERMINAL_HEIGHT_KEY = "workspace-terminal-height";
const MIN_FILES_WIDTH = 240;
const MAX_FILES_WIDTH = 520;
function clampTerminalHeight(value: number) {
  const available = window.innerHeight - (window.innerWidth <= 700 ? 300 : 220);
  const maximum = Math.max(120, Math.min(Math.round(window.innerHeight * 0.7), available));
  const minimum = Math.min(180, maximum);
  return Math.max(minimum, Math.min(maximum, Math.round(value)));
}
const text = (value: unknown) =>
  typeof value === "string" ? value : JSON.stringify(value ?? "");
const DEFAULT_APP_SETTINGS: AppSettings = {
  title_provider: "openai",
  title_model: "gpt-6-luna",
  theme_color: "#25262A",
};

const MODEL_ORDER = [
  "gpt-6-astra",
  "gpt-6.1-sol",
  "gpt-6-sol",
  "gpt-6-luna",
  "gpt-5.6-sol",
  "gpt-5.6-terra",
  "gpt-5.6-luna",
];

/** Model preselected for new chats when the provider offers it (Azure: any deployment of it). */
const DEFAULT_MODEL = "gpt-6.1-sol";

function defaultModelId(models: Model[]) {
  return (models.find((item) => item.model === DEFAULT_MODEL) ?? models[0])?.id ?? "";
}

const HISTORY_INITIAL_COUNT = 5;
const HISTORY_PAGE_SIZE = 10;
const REASONING_EFFORT_LABELS: Record<string, string> = {
  none: "Instant",
  low: "Light",
  medium: "Medium",
  high: "High",
  xhigh: "Extra High",
  max: "Max",
};

type ModelFamilyIconName = "astra" | "sol" | "terra" | "luna";

function modelFamilyIconName(model: string): ModelFamilyIconName | undefined {
  const family = model.toLowerCase().match(/-(astra|sol|terra|luna)$/)?.[1];
  return family as ModelFamilyIconName | undefined;
}

function reasoningEffortLabel(value: string) {
  return REASONING_EFFORT_LABELS[value] || value;
}

function modelDisplayLabel(model: Model) {
  return model.connection_label ? `${model.label} · ${model.connection_label}` : model.label;
}

function orderedModels(models: Model[]): Model[] {
  const rank = (model: Model) => {
    const index = MODEL_ORDER.indexOf(model.model);
    return index < 0 ? MODEL_ORDER.length : index;
  };
  return [...models].sort((a, b) => rank(a) - rank(b));
}

/** The first model of each family (in display order) is shown; the rest go under "More models". */
function splitModelsByFamily(models: Model[]): { primary: Model[]; more: Model[] } {
  const seen = new Set<string>();
  const primary: Model[] = [];
  const more: Model[] = [];
  for (const model of orderedModels(models)) {
    const family = modelFamilyIconName(model.model) ?? model.model;
    (seen.has(family) ? more : primary).push(model);
    seen.add(family);
  }
  return { primary, more };
}

function themeVariables(color: string): CSSProperties {
  const match = /^#([0-9a-f]{6})$/i.exec(color);
  if (!match) return {};
  const value = Number.parseInt(match[1], 16);
  const rgb = [(value >> 16) & 255, (value >> 8) & 255, value & 255];
  const linear = rgb.map((channel) => {
    const normalized = channel / 255;
    return normalized <= 0.03928 ? normalized / 12.92 : ((normalized + 0.055) / 1.055) ** 2.4;
  });
  const luminance = 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
  const foreground = luminance > 0.179 ? "#17181B" : "#FFFFFF";
  const target = luminance > 0.179 ? 0 : 255;
  const hover = `rgb(${rgb.map((channel) => Math.round(channel * 0.86 + target * 0.14)).join(" ")})`;
  return {
    "--theme-color": color,
    "--theme-foreground": foreground,
    "--theme-hover": hover,
  } as CSSProperties;
}

function elapsedLabel(seconds: number) {
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return remainder ? `${minutes}m ${remainder}s` : `${minutes}m`;
}

/** UI icons from Lucide (ISC License, https://lucide.dev); names are app-level aliases. */
const ICONS = {
  "panel-right": PanelRight,
  terminal: SquareTerminal,
  "chevron-right": ChevronRight,
  "chevron-down": ChevronDown,
  compose: SquarePen,
  search: Search,
  folder: Folder,
  "folder-open": FolderOpen,
  pin: Pin,
  refresh: RefreshCw,
  paperclip: Paperclip,
  globe: Globe,
  check: Check,
  close: X,
  copy: Copy,
  spark: Sparkles,
  gear: Settings,
  plus: Plus,
  "arrow-up": ArrowUp,
} satisfies Record<string, LucideIcon>;

type IconName = keyof typeof ICONS;

function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
  const Component = ICONS[name];
  return <Component aria-hidden="true" data-icon={name} size={size} strokeWidth={1.8} />;
}

function CopyButton({ content, tooltip }: { content: string; tooltip: string }) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  const label = state === "copied" ? "Copied" : state === "failed" ? "Copy failed" : tooltip;

  async function copy() {
    try {
      await navigator.clipboard.writeText(content);
      setState("copied");
      window.setTimeout(() => setState("idle"), 1200);
    } catch {
      setState("failed");
      window.setTimeout(() => setState("idle"), 1200);
    }
  }

  return (
    <button
      className="message-copy"
      type="button"
      data-state={state}
      data-tooltip={label}
      aria-label={label}
      onClick={() => void copy()}
    >
      {state === "copied" ? <Icon name="check" size={18} /> : <Icon name="copy" size={18} />}
      <span className="sr-only">{label}</span>
    </button>
  );
}

type PopoverSelectOption = { value: string; label: string; icon?: ModelFamilyIconName };

/**
 * Model family marks: one filled silhouette per family on a tinted tile, drawn on a
 * 24px grid without hairlines so each stays legible at 18px.
 */
const MODEL_FAMILY_MARKS: Record<ModelFamilyIconName, ReactNode> = {
  astra: <path d="M12 2.5C12.9 8.1 15.9 11.1 21.5 12 15.9 12.9 12.9 15.9 12 21.5 11.1 15.9 8.1 12.9 2.5 12 8.1 11.1 11.1 8.1 12 2.5Z" />,
  sol: <>
    <circle cx="12" cy="12" r="5" />
    <path d="M12 2.5v1.6M12 19.9v1.6M2.5 12h1.6M19.9 12h1.6M5.3 5.3l1.1 1.1M17.6 17.6l1.1 1.1M18.7 5.3l-1.1 1.1M6.4 17.6l-1.1 1.1"
      fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
  </>,
  terra: <>
    <circle cx="12" cy="12" r="5.6" />
    <ellipse cx="12" cy="12" rx="10.2" ry="3.4" transform="rotate(-22 12 12)" fill="none" stroke="currentColor" strokeWidth="1.9" />
  </>,
  luna: <path d="M15.2 3.2a9 9 0 1 0 5.6 14.4A7.4 7.4 0 0 1 15.2 3.2Z" />,
};

function ModelFamilyIcon({ name, size = "sm" }: { name: ModelFamilyIconName; size?: "sm" | "md" }) {
  return (
    <span aria-hidden="true" className={`model-family-icon model-family-icon-${name} model-family-icon-${size}`} data-model-icon={name}>
      <svg viewBox="0 0 24 24" fill="currentColor">{MODEL_FAMILY_MARKS[name]}</svg>
    </span>
  );
}

type PopoverRow = { kind: "option"; option: PopoverSelectOption } | { kind: "more" };

/**
 * Listbox popover. `moreOptions` sit behind a "More …" row that expands in place; it
 * starts expanded when the current value is one of them.
 */
function PopoverSelect({ label, value, options, moreOptions = [], moreLabel = "More", onChange, disabled = false, className = "" }: {
  label: string;
  value: string;
  options: PopoverSelectOption[];
  moreOptions?: PopoverSelectOption[];
  moreLabel?: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const menuId = `popover-select-${useId().replace(/:/g, "")}`;
  const selectedInMore = moreOptions.some((option) => option.value === value);
  const rows: PopoverRow[] = [
    ...options.map((option) => ({ kind: "option" as const, option })),
    ...(moreOptions.length ? [{ kind: "more" as const }] : []),
    ...(expanded ? moreOptions.map((option) => ({ kind: "option" as const, option })) : []),
  ];
  const selectedIndex = rows.findIndex((row) => row.kind === "option" && row.option.value === value);
  const selectedOption = [...options, ...moreOptions].find((option) => option.value === value);
  const selectedLabel = selectedOption?.label || value;

  useEffect(() => {
    if (!open) return;
    const closeOnOutsidePointer = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", closeOnOutsidePointer);
    return () => document.removeEventListener("pointerdown", closeOnOutsidePointer);
  }, [open]);

  useEffect(() => {
    if (open) listRef.current?.focus();
  }, [open]);

  const revealMore = useRef(false);
  useEffect(() => {
    if (!expanded || !revealMore.current) return;
    revealMore.current = false;
    // Bring the newly listed models into view inside the height-capped menu.
    listRef.current?.querySelector<HTMLElement>(".popover-select-more")?.scrollIntoView?.({ block: "start", behavior: "smooth" });
  }, [expanded]);

  function close() {
    setOpen(false);
    triggerRef.current?.focus();
  }

  function activate(index: number) {
    const row = rows[index];
    if (!row) return;
    if (row.kind === "more") {
      revealMore.current = !expanded;
      setExpanded((value) => !value);
      setActiveIndex(index);
      return;
    }
    onChange(row.option.value);
    close();
  }

  function openMenu(toEnd = false) {
    if (disabled || rows.length === 0) return;
    const showMore = selectedInMore;
    setExpanded(showMore);
    const visible = options.length + (moreOptions.length ? 1 : 0) + (showMore ? moreOptions.length : 0);
    const current = showMore && selectedInMore
      ? options.length + 1 + moreOptions.findIndex((option) => option.value === value)
      : options.findIndex((option) => option.value === value);
    setActiveIndex(toEnd ? visible - 1 : Math.max(0, current));
    setOpen(true);
  }

  function handleTriggerKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      close();
      return;
    }
    if (["Enter", " ", "ArrowDown", "ArrowUp"].includes(event.key)) {
      event.preventDefault();
      openMenu(event.key === "ArrowUp");
    }
  }

  function handleListKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      close();
      return;
    }
    if (event.key === "Tab") {
      setOpen(false);
      return;
    }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      setActiveIndex((index) => Math.max(0, Math.min(rows.length - 1, index + (event.key === "ArrowDown" ? 1 : -1))));
      return;
    }
    if (event.key === "Home" || event.key === "End") {
      event.preventDefault();
      setActiveIndex(event.key === "Home" ? 0 : rows.length - 1);
      return;
    }
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      activate(activeIndex);
    }
  }

  const renderOption = (option: PopoverSelectOption, index: number) => (
    <button
      className={`popover-select-option ${index === activeIndex ? "is-active" : ""}`}
      id={`${menuId}-option-${index}`}
      key={option.value}
      type="button"
      role="option"
      tabIndex={-1}
      aria-selected={option.value === value}
      onMouseDown={(event) => event.preventDefault()}
      onClick={() => activate(index)}
    >
      <span className="popover-select-option-label">
        {option.icon && <ModelFamilyIcon name={option.icon} size="md" />}
        <span>{option.label}</span>
      </span>
      {option.value === value && <Icon name="check" size={15} />}
    </button>
  );

  return (
    <div className={`popover-select ${className}`.trim()} ref={rootRef}>
      <button
        ref={triggerRef}
        className="popover-select-trigger"
        type="button"
        aria-label={label}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={menuId}
        disabled={disabled}
        onClick={() => (open ? close() : openMenu())}
        onKeyDown={handleTriggerKeyDown}
      >
        <span className="popover-select-value">
          {selectedOption?.icon && <ModelFamilyIcon name={selectedOption.icon} />}
          <span>{selectedLabel}</span>
        </span>
        <Icon name="chevron-down" size={14} />
      </button>
      {open && (
        <div
          ref={listRef}
          className="popover-select-menu"
          id={menuId}
          role="listbox"
          tabIndex={-1}
          aria-label={label}
          aria-activedescendant={rows[activeIndex] ? `${menuId}-option-${activeIndex}` : undefined}
          onKeyDown={handleListKeyDown}
        >
          {rows.map((row, index) => row.kind === "option" ? renderOption(row.option, index) : (
            <button
              className={`popover-select-option popover-select-more ${index === activeIndex ? "is-active" : ""}`}
              id={`${menuId}-option-${index}`}
              key="more"
              type="button"
              role="option"
              tabIndex={-1}
              aria-selected={false}
              aria-expanded={expanded}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => activate(index)}
            >
              <span className="popover-select-option-label">
                <span>{moreLabel}</span>
                <small>{moreOptions.length}</small>
              </span>
              <span className={`popover-select-more-chevron ${expanded ? "is-expanded" : ""}`}><Icon name="chevron-right" size={14} /></span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/** Ordered levels as a stepped slider, like the effort control in Codex and Claude. */
export function EffortSlider({ value, levels, onChange, disabled = false }: {
  value: string;
  levels: string[];
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const sliderRef = useRef<HTMLInputElement>(null);
  const panelId = `effort-${useId().replace(/:/g, "")}`;
  const index = Math.max(0, levels.indexOf(value));
  const level = levels.length > 1 ? index / (levels.length - 1) : 1;

  useEffect(() => {
    if (!open) return;
    sliderRef.current?.focus();
    const closeOnOutsidePointer = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", closeOnOutsidePointer);
    return () => document.removeEventListener("pointerdown", closeOnOutsidePointer);
  }, [open]);

  function close() {
    setOpen(false);
    triggerRef.current?.focus();
  }

  return (
    <div className="effort-slider" ref={rootRef}>
      <button
        ref={triggerRef}
        className="popover-select-trigger effort-trigger"
        type="button"
        aria-label="Reasoning effort"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={panelId}
        disabled={disabled || levels.length === 0}
        onClick={() => (open ? close() : setOpen(true))}
      >
        <span className="effort-meter" aria-hidden="true">
          {[0, 1, 2, 3].map((bar) => (
            <span key={bar} className={bar / 3 <= level + 1e-9 ? "is-on" : undefined} />
          ))}
        </span>
        <span>{reasoningEffortLabel(value)}</span>
        <Icon name="chevron-down" size={14} />
      </button>
      {open && (
        <div className="effort-panel" id={panelId} role="dialog" aria-label="Reasoning effort"
          onKeyDown={(event) => {
            if (event.key === "Escape" || event.key === "Enter") {
              event.preventDefault();
              close();
            }
          }}>
          <div className="effort-panel-header">
            <span>Reasoning effort</span>
            <strong>{reasoningEffortLabel(value)}</strong>
          </div>
          <input
            ref={sliderRef}
            type="range"
            min={0}
            max={Math.max(0, levels.length - 1)}
            step={1}
            value={index}
            aria-label="Reasoning effort"
            aria-valuetext={reasoningEffortLabel(value)}
            style={{ "--effort-fill": `${level * 100}%` } as CSSProperties}
            onChange={(event) => onChange(levels[Number(event.target.value)])}
          />
          <div className="effort-ticks">
            {levels.map((item, position) => {
              const ratio = levels.length > 1 ? position / (levels.length - 1) : 0;
              const edge = position === 0 ? "is-first" : position === levels.length - 1 ? "is-last" : "";
              return (
                <button key={item} type="button" className={`${edge} ${position === index ? "is-current" : ""}`.trim() || undefined}
                  style={{ "--tick": ratio } as CSSProperties} tabIndex={-1} onClick={() => onChange(item)}>
                  {item === "xhigh" ? "X-High" : reasoningEffortLabel(item)}
                </button>
              );
            })}
          </div>
          <div className="effort-hint" aria-hidden="true"><span>Faster</span><span>Smarter</span></div>
        </div>
      )}
    </div>
  );
}

type FileKind = "pdf" | "image" | "document" | "spreadsheet" | "presentation" | "code" | "archive" | "generic";

function fileKind(name: string): FileKind {
  const extension = name.toLowerCase().split(".").pop() || "";
  if (extension === "pdf") return "pdf";
  if (["png", "jpg", "jpeg", "gif", "webp", "svg", "heic", "bmp", "tif", "tiff"].includes(extension)) return "image";
  if (["doc", "docx", "odt", "rtf", "txt", "md"].includes(extension)) return "document";
  if (["xls", "xlsx", "ods", "csv", "tsv"].includes(extension)) return "spreadsheet";
  if (["ppt", "pptx", "odp", "key"].includes(extension)) return "presentation";
  if (["js", "jsx", "ts", "tsx", "py", "rb", "go", "rs", "java", "c", "cc", "cpp", "h", "hpp", "css", "html", "json", "yaml", "yml", "toml", "xml", "sql", "sh"].includes(extension)) return "code";
  if (["zip", "gz", "tgz", "tar", "bz2", "xz", "7z", "rar"].includes(extension)) return "archive";
  return "generic";
}

function formatFileSize(size: number) {
  if (size < 1024) return `${size} B`;
  const units = ["KB", "MB", "GB"];
  let value = size / 1024;
  let unit = units[0];
  for (let index = 1; index < units.length && value >= 1024; index += 1) {
    value /= 1024;
    unit = units[index];
  }
  return `${value >= 10 ? Math.round(value) : value.toFixed(1)} ${unit}`;
}

const FILE_ICONS: Record<FileKind, LucideIcon> = {
  pdf: FileText,
  image: FileImage,
  document: FileText,
  spreadsheet: FileSpreadsheet,
  presentation: Presentation,
  code: FileCode,
  archive: FileArchive,
  generic: File,
};

function FileTypeIcon({ name }: { name: string }) {
  const kind = fileKind(name);
  const Component = FILE_ICONS[kind];
  return (
    <span className={`file-type-icon file-type-${kind}`}>
      <Component aria-hidden="true" data-icon={`file-${kind}`} size={16} strokeWidth={1.8} />
    </span>
  );
}

const WORKSPACE_FILE_MIME = "application/x-chat-workspace-file";

function FileTree({ entries, childrenByPath, expanded, loading, errors, onToggle, onRetry, conversationId, depth = 0 }: {
  entries: WorkspaceFile[];
  childrenByPath: Record<string, WorkspaceFile[]>;
  expanded: string[];
  loading: string[];
  errors: Record<string, string>;
  onToggle: (entry: WorkspaceFile) => void;
  onRetry: (path: string) => void;
  conversationId: string;
  depth?: number;
}) {
  function startDrag(event: ReactDragEvent<HTMLButtonElement>, entry: WorkspaceFile) {
    event.dataTransfer.effectAllowed = "copy";
    event.dataTransfer.setData(WORKSPACE_FILE_MIME, JSON.stringify({ conversationId, path: entry.path }));
  }
  return (
    <ul className={depth ? "file-tree file-tree-children" : "file-tree"}>
      {entries.map((entry) => {
        const isExpanded = expanded.includes(entry.path);
        if (!entry.directory) return (
          <li key={entry.path}>
            <button className="file-tree-row file-tree-file" type="button" draggable title={`${entry.path} — Drag to the message input`}
              onDragStart={(event) => startDrag(event, entry)}>
              <span className="file-tree-spacer" />
              <FileTypeIcon name={entry.name} />
              <span className="file-tree-name">{entry.name}</span>
              <small>{formatFileSize(entry.size)}</small>
            </button>
          </li>
        );
        const children = childrenByPath[entry.path];
        const isLoading = loading.includes(entry.path);
        const error = errors[entry.path];
        return (
          <li key={entry.path}>
            <button className="file-tree-row file-tree-directory" type="button" draggable aria-expanded={isExpanded} onClick={() => onToggle(entry)} title={`${entry.path} — Click to expand or collapse; drag to the message input`} onDragStart={(event) => startDrag(event, entry)}>
              <span className={`file-tree-chevron ${isExpanded ? "is-expanded" : ""}`}><Icon name="chevron-right" size={13} /></span>
              <span className="folder-icon"><Icon name={isExpanded ? "folder-open" : "folder"} size={17} /></span>
              <span className="file-tree-name">{entry.name}</span>
            </button>
            {isExpanded && (
              <div className="file-tree-branch" aria-busy={isLoading || undefined}>
                {isLoading && <div className="file-tree-state" role="status"><span className="file-tree-spinner" />Loading…</div>}
                {!isLoading && error && <div className="file-tree-state file-tree-error" role="alert"><span>Couldn’t load folder.</span><button type="button" aria-label={`Retry loading ${entry.name}`} onClick={() => onRetry(entry.path)}>Retry</button></div>}
                {!isLoading && !error && children?.length === 0 && <div className="file-tree-state">Empty folder</div>}
                {!isLoading && !error && children && <FileTree entries={children} childrenByPath={childrenByPath} expanded={expanded} loading={loading} errors={errors} onToggle={onToggle} onRetry={onRetry} conversationId={conversationId} depth={depth + 1} />}
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}

type SettingsPage = "chat" | "settings" | "cost" | "theme";

function SettingsPanel({
  page,
  config,
  settings,
  costs,
  onNavigate,
  onChange,
}: {
  page: SettingsPage;
  config: Config | null;
  settings: AppSettings;
  costs: CostSummary | null;
  onNavigate: (page: SettingsPage) => void;
  onChange: (changes: Partial<AppSettings>) => Promise<void>;
}) {
  const provider = config?.providers.find((item) => item.id === settings.title_provider);
  const presets = ["#25262A", "#315C47", "#315B7A", "#5B4B8A", "#8A493D", "#B78A2B"];
  const money = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 4, maximumFractionDigits: 6 });
  const currentMonth = new Date().toISOString().slice(0, 7);
  const current = costs?.months.find((item) => item.month === currentMonth)?.usd || 0;
  if (page === "cost") return (
    <section className="settings-page">
      <button className="settings-back" type="button" onClick={() => onNavigate("settings")}>← Settings</button>
      <h1>Cost</h1>
      <p className="settings-description">Monthly estimated LLM token costs in USD.</p>
      <div className="cost-current"><span>This month</span><strong>{money.format(current)}</strong></div>
      <div className="cost-notes"><span>Estimated</span><span>LLM token costs only</span><span>Tool fees excluded</span><span>UTC</span></div>
      <div className="cost-list" aria-label="Monthly costs">
        {(costs?.months || []).map((item) => <div className="cost-row" key={item.month}><span>{item.month}</span><strong>{money.format(item.usd)}</strong></div>)}
      </div>
    </section>
  );
  if (page === "theme") return (
    <section className="settings-page">
      <button className="settings-back" type="button" onClick={() => onNavigate("settings")}>← Settings</button>
      <h1>Theme color</h1>
      <p className="settings-description">Applied to your message boxes and the send button.</p>
      <div className="theme-swatches" aria-label="Theme color presets">
        {presets.map((color) => <button key={color} type="button" aria-label={`Use ${color}`} aria-pressed={settings.theme_color === color} style={{ backgroundColor: color }} onClick={() => void onChange({ theme_color: color })} />)}
      </div>
      <label className="custom-color">Custom color<input type="color" aria-label="Custom theme color" value={settings.theme_color} onChange={(event) => void onChange({ theme_color: event.target.value.toUpperCase() })} /><code>{settings.theme_color}</code></label>
      <div className="theme-preview"><div className="user-message"><p>Theme preview</p></div><button className="send" type="button" aria-label="Theme preview send"><Icon name="arrow-up" size={17} /></button></div>
    </section>
  );
  return (
    <section className="settings-page">
      <button className="settings-back" type="button" onClick={() => onNavigate("chat")}>← Back to chat</button>
      <h1>Settings</h1>
      <div className="title-model-setting">
        <h2>Title model</h2>
        <p className="settings-description">Generates a concise title from the first message.</p>
        <div className="title-model-controls">
          <label>Provider<select aria-label="Title provider" value={settings.title_provider} onChange={(event) => {
            const nextProvider = config?.providers.find((item) => item.id === event.target.value);
            const nextModel = nextProvider?.models[0]?.id;
            if (nextModel) void onChange({ title_provider: event.target.value, title_model: nextModel });
          }}>{config?.providers.map((item) => <option key={item.id} value={item.id} disabled={!item.enabled}>{item.label}{!item.enabled ? " (unavailable)" : ""}</option>)}</select></label>
          <label>Model<select aria-label="Title model" value={settings.title_model} onChange={(event) => void onChange({ title_provider: settings.title_provider, title_model: event.target.value })}>{orderedModels(provider?.models || []).map((item) => <option key={item.id} value={item.id}>{modelDisplayLabel(item)}{item.id !== item.model ? ` · ${item.deployment || item.id}` : ""}</option>)}</select></label>
        </div>
      </div>
      <div className="settings-links">
        <button type="button" onClick={() => onNavigate("cost")}><span><strong>Cost</strong><small>Monthly estimated usage</small></span><Icon name="chevron-right" /></button>
        <button type="button" onClick={() => onNavigate("theme")}><span><strong>Theme color</strong><small>{settings.theme_color}</small></span><Icon name="chevron-right" /></button>
      </div>
    </section>
  );
}

function Choices({
  label,
  items,
  selected,
  change,
  disabled,
}: {
  label: string;
  items: Named[];
  selected: string[];
  change: (ids: string[]) => void;
  disabled: boolean;
}) {
  if (!items.length) return null;
  return (
    <fieldset disabled={disabled}>
      <legend>{label}</legend>
      {items.map((item) => (
        <button
          className={`tool-option ${selected.includes(item.id) ? "is-selected" : ""}`}
          key={item.id}
          type="button"
          aria-pressed={selected.includes(item.id)}
          disabled={disabled}
          onClick={() => change(selected.includes(item.id)
            ? selected.filter((id) => id !== item.id)
            : [...selected, item.id])}
        >
          <Icon name="spark" />
          <span>{item.label}</span>
          {selected.includes(item.id) && <Icon name="check" size={16} />}
        </button>
      ))}
    </fieldset>
  );
}

function WorkGroup({ actions, timeline, status, active }: {
  actions: AgentEvent[];
  timeline: AgentEvent[];
  status: string;
  active: boolean;
}) {
  const category = (action: AgentEvent) => action.type === "command" ? "command" :
    action.type === "patch" ? "edit" :
    action.type === "image_view" ? "image" :
    action.type === "approval" ? "approval" :
      action.data.type === "web_search_call" ? "web" : "tool";
  const categories = [...new Set(actions.map(category))];
  const commandDone = (action: AgentEvent) => timeline.find((event) =>
    event.type === "command_done" && event.data.call_id === action.data.call_id &&
    event.data.index === action.data.index);
  const toolResult = (action: AgentEvent) => timeline.find((event) =>
    event.type === "tool_result" && event.data.id === action.data.id);
  const patchDone = (action: AgentEvent) => timeline.find((event) =>
    event.type === "patch_done" && event.data.call_id === action.data.call_id);
  const imageDone = (action: AgentEvent) => timeline.find((event) =>
    event.type === "image_view_done" && event.data.call_id === action.data.call_id);
  const runningCommand = !terminal(status) ? [...actions].reverse().find((action) =>
    action.type === "command" && !commandDone(action)) : undefined;
  const labels = categories.map((kind) => {
    const matching = actions.filter((action) => category(action) === kind);
    const running = !terminal(status) && matching.some((action) =>
      kind === "command" ? !commandDone(action) : kind === "edit" ? !patchDone(action) :
        kind === "image" ? !imageDone(action) :
        kind !== "approval" && !toolResult(action));
    const label = kind === "command" ? (running ? "Running commands" : "Ran commands") :
      kind === "edit" ? (running ? "Editing files" : "Edited files") :
      kind === "image" ? (running ? "Viewing images" : "Viewed images") :
      kind === "web" ? (running ? "Searching web" : "Searched web") :
        kind === "tool" ? (running ? "Using external tools" : "Used external tools") : "Requested approval";
    return { kind, label, running };
  });
  return (
    <details className="work-group">
      <summary>
        <span className="work-chevron" aria-hidden="true"><Icon name="chevron-right" size={14} /></span>
        <span className="work-summary-content">
          {labels.map(({ kind, label, running }, index) => (
            <span key={kind}>
              {index > 0 && ", "}
              <span className={active && running ? "activity-shimmer" : undefined}>{label}</span>
            </span>
          ))}
          {runningCommand && (
            <span className="work-command-preview" title={text(runningCommand.data.command)}>
              {" "}{text(runningCommand.data.command).replace(/\s+/g, " ").trim()}
            </span>
          )}
        </span>
      </summary>
      <div className="work-details">
        {actions.map((action) => {
          if (action.type === "command") {
            const output = timeline.filter((event) => event.type === "command_output" &&
              event.data.call_id === action.data.call_id && event.data.index === action.data.index);
            const done = commandDone(action);
            const outcome = done?.data.outcome as Record<string, unknown> | undefined;
            const timeoutSeconds = outcome?.timeout_seconds ?? action.data.timeout_seconds;
            const result = outcome?.type === "exit" ? `Exit code ${text(outcome.exit_code)}` :
              outcome?.type === "timeout" ? `Command timed out${timeoutSeconds != null ? ` (limit: ${text(timeoutSeconds)}s)` : ""}` :
              outcome?.type ? text(outcome.type) : done ? "Completed" : terminal(status) ? "Interrupted" : "Running…";
            return (
              <div className="work-detail" key={action.seq}>
                <div className="work-detail-title">Command</div>
                <pre className="command-code">$ {text(action.data.command)}</pre>
                {output.length > 0 && <pre className="command-output">{output.map((event) => text(event.data.text)).join("")}</pre>}
                <small>{result}</small>
              </div>
            );
          }
          if (action.type === "patch") {
            const done = patchDone(action);
            const operation = text(action.data.operation);
            const verb = operation === "create_file" ? "Create" : operation === "delete_file" ? "Delete" : "Edit";
            return (
              <div className="work-detail" key={action.seq}>
                <div className="work-detail-title">{verb} · {text(done?.data.path || action.data.path)}</div>
                {Boolean(done?.data.diff) && <DiffView diff={text(done?.data.diff)} dark />}
                <small>
                  {done ? (done.data.status === "completed" ? text(done.data.output) : `Failed: ${text(done.data.output)}`) :
                    terminal(status) ? "Interrupted" : "Applying…"}
                </small>
              </div>
            );
          }
          if (action.type === "image_view") {
            const done = imageDone(action);
            const thumbnail = text(done?.data.thumbnail);
            const size = done?.data.width ? `${text(done.data.width)}×${text(done.data.height)}` : "";
            return (
              <div className="work-detail" key={action.seq}>
                <div className="work-detail-title">View image · {text(done?.data.path || action.data.path)}</div>
                {thumbnail.startsWith("data:image/") && (
                  <img className="image-view-thumbnail" src={thumbnail} alt={`Image viewed by the model: ${text(done?.data.path)}`} />
                )}
                <small>
                  {done ? (done.data.status === "completed" ? [size, text(done.data.mime)].filter(Boolean).join(" · ") :
                    `Failed: ${text(done.data.output)}`) : terminal(status) ? "Interrupted" : "Loading…"}
                </small>
              </div>
            );
          }
          if (action.type === "tool") {
            const result = toolResult(action);
            const title = action.data.type === "web_search_call" ? "Web search" :
              text(action.data.name || action.data.server_label || "External tool");
            return (
              <div className="work-detail" key={action.seq}>
                <div className="work-detail-title">{title}</div>
                {Boolean(result?.data.output || result?.data.error) &&
                  <pre className="command-output">{text(result?.data.output || result?.data.error)}</pre>}
                {Boolean(result?.data.status) && <small>{text(result?.data.status)}</small>}
              </div>
            );
          }
          return (
            <div className="work-detail" key={action.seq}>
              <div className="work-detail-title">Approval requested</div>
              <small>{text(action.data.server_label || "External tool")} / {text(action.data.name)}</small>
            </div>
          );
        })}
      </div>
    </details>
  );
}

/** Unified diff with per-line coloring; file headers are omitted. */
export function DiffView({ diff, dark = false }: { diff: string; dark?: boolean }) {
  const lines = diff.split("\n").filter((line) =>
    !/^(diff --git|index |--- |\+\+\+ |new file mode|deleted file mode|old mode|new mode)/.test(line));
  return (
    <pre className={`diff-view${dark ? " diff-dark" : ""}`}>
      {lines.map((line, index) => (
        <span key={index} className={line.startsWith("@@") ? "diff-hunk" : line.startsWith("+") ? "diff-add" :
          line.startsWith("-") ? "diff-del" : undefined}>{line || " "}{"\n"}</span>
      ))}
    </pre>
  );
}

interface ChangedFile { path: string; status: string; added: number | null; removed: number | null; binary: boolean }
interface RunChangesState { available: boolean; reverted?: boolean; files: ChangedFile[]; skipped_count?: number }

/** Files changed by a finished run, with per-file diffs and checkpoint undo. */
export function RunChanges({ runId, timeline }: { runId: string; timeline: AgentEvent[] }) {
  const ready = timeline.some((event) => event.type === "checkpoint" && event.data.name === "after" && !event.data.error);
  const [state, setState] = useState<RunChangesState | null>(null);
  const [diffs, setDiffs] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!ready) return;
    let cancelled = false;
    api<RunChangesState>(`/runs/${runId}/changes`).then((value) => { if (!cancelled) setState(value); })
      .catch((e) => { if (!cancelled) setError(String(e)); });
    return () => { cancelled = true; };
  }, [ready, runId]);
  if (!ready || !state?.available || state.files.length === 0) return error ? <p role="alert" className="error">{error}</p> : null;
  const added = state.files.reduce((sum, file) => sum + (file.added ?? 0), 0);
  const removed = state.files.reduce((sum, file) => sum + (file.removed ?? 0), 0);
  async function toggle(path: string, open: boolean) {
    if (!open || diffs[path] !== undefined) return;
    try {
      const result = await api<{ diff: string }>(`/runs/${runId}/diff?path=${encodeURIComponent(path)}`);
      setDiffs((current) => ({ ...current, [path]: result.diff }));
    } catch (e) {
      setDiffs((current) => ({ ...current, [path]: `Could not load diff: ${String(e)}` }));
    }
  }
  async function revert() {
    if (!window.confirm(`Undo this run's changes to ${state!.files.length} files?`)) return;
    setBusy(true);
    setError("");
    try {
      let response = await fetch(`/api/runs/${runId}/revert`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}),
      });
      if (response.status === 409) {
        const body = await response.json();
        const conflicts: string[] = body.detail?.conflicts ?? [];
        if (!window.confirm(`These files changed after the run:\n${conflicts.slice(0, 10).join("\n")}\n\nOverwrite them with the state before the run?`)) return;
        response = await fetch(`/api/runs/${runId}/revert`, {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ force: true }),
        });
      }
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(typeof body.detail === "string" ? body.detail : `Request failed (${response.status})`);
      }
      setState(await api<RunChangesState>(`/runs/${runId}/changes`));
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="run-changes" aria-label="Changed files">
      <header>
        <strong>{state.files.length} {state.files.length === 1 ? "file" : "files"} changed</strong>
        <span className="diff-count-add">+{added}</span>
        <span className="diff-count-del">−{removed}</span>
        {state.reverted ? <span className="run-changes-reverted">Reverted</span> : (
          <button type="button" className="run-changes-undo" disabled={busy} onClick={() => void revert()}>
            {busy ? "Undoing…" : "Undo"}
          </button>
        )}
      </header>
      <ul>
        {state.files.map((file) => (
          <li key={file.path}>
            <details onToggle={(event) => void toggle(file.path, event.currentTarget.open)}>
              <summary>
                <span className={`change-status change-${file.status}`}>{file.status === "added" ? "A" : file.status === "deleted" ? "D" : "M"}</span>
                <span className="change-path" title={file.path}>{file.path}</span>
                {file.binary ? <small>binary</small> : (
                  <small><span className="diff-count-add">+{file.added}</span> <span className="diff-count-del">−{file.removed}</span></small>
                )}
              </summary>
              {diffs[file.path] === undefined ? <p className="change-loading">Loading…</p> :
                file.binary ? <p className="change-loading">Binary file</p> : <DiffView diff={diffs[file.path]} />}
            </details>
          </li>
        ))}
      </ul>
      {Boolean(state.skipped_count) && (
        <small className="run-changes-note">{state.skipped_count} large files are not covered by checkpoints.</small>
      )}
      {error && <p role="alert" className="error">{error}</p>}
    </section>
  );
}

function formatTokens(value: number) {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(value >= 10_000_000 ? 0 : 2)}M`;
  if (value >= 1000) return `${(value / 1000).toFixed(value >= 100_000 ? 0 : 1)}K`;
  return String(value);
}

/** Context fill relative to the auto-compaction threshold, with the model limit in the tooltip. */
/** Shown both in Activity and, once finished, as a persistent divider in the turn. */
function CompactionNotice({ compaction, active }: { compaction: Compaction; active: boolean }) {
  const sizes = compaction.before && compaction.after
    ? ` · ${formatTokens(compaction.before)} → ${formatTokens(compaction.after)} tokens`
    : compaction.before ? ` · ${formatTokens(compaction.before)} tokens` : "";
  const label = compaction.done ? "Context automatically compacted" : active ? "Compacting context…" : "Context compaction interrupted";
  return (
    <div className={`compaction-notice${compaction.done ? "" : " is-running"}`} role={compaction.done ? undefined : "status"}
      title={compaction.threshold ? `Compacts when the context reaches ${formatTokens(compaction.threshold)} tokens` : undefined}>
      <span className="compaction-line" aria-hidden="true" />
      <span className={active && !compaction.done ? "activity-shimmer" : undefined}>{label}{sizes}</span>
      <span className="compaction-line" aria-hidden="true" />
    </div>
  );
}

export function ContextRing({ tokens, compacted, compacting = false, threshold, modelLimit }: {
  tokens: number | null;
  compacted: boolean;
  compacting?: boolean;
  threshold: number;
  modelLimit?: number;
}) {
  const limit = Math.min(threshold, modelLimit ?? threshold);
  const ratio = tokens === null ? 0 : Math.min(1, tokens / limit);
  const percent = Math.round(ratio * 100);
  const level = ratio >= 0.9 ? "high" : ratio >= 0.7 ? "medium" : "low";
  const radius = 7;
  const circumference = 2 * Math.PI * radius;
  const label = compacting
    ? "Compacting the conversation context…"
    : tokens === null
    ? "Context compacted; usage updates after the next response"
    : `Context ${percent}% used · ${formatTokens(tokens)} / ${formatTokens(limit)} tokens before auto-compaction` +
      (modelLimit ? ` · model input limit ${formatTokens(modelLimit)}` : "") +
      (compacted ? " · compacted earlier" : "");
  return (
    <span className={`context-ring context-ring-${level}${compacting ? " is-compacting" : ""}`} role="img" aria-label={label} data-tooltip={label} tabIndex={0}>
      <svg width="20" height="20" viewBox="0 0 20 20" aria-hidden="true">
        <circle className="context-ring-track" cx="10" cy="10" r={radius} />
        <circle className="context-ring-value" cx="10" cy="10" r={radius}
          strokeDasharray={circumference} strokeDashoffset={circumference * (1 - ratio)} />
      </svg>
      <span className="context-ring-text">{compacting ? "Compacting" : tokens === null ? "—" : `${percent}%`}</span>
    </span>
  );
}

const PREVIEWABLE_IMAGE = /^image\/(png|jpeg|gif|webp)$/;

/** Files sent with a message; each chip downloads the original upload. */
function RunAttachments({ run }: { run: Run }) {
  const attachments = run.attachments ?? [];
  const missing = run.request.attachment_ids.length - attachments.length;
  if (!attachments.length && missing <= 0) return null;
  return (
    <ul className="message-attachments" aria-label="Attachments">
      {attachments.map((attachment) => {
        const url = `/api/conversations/${encodeURIComponent(run.conversation_id)}/attachments/${encodeURIComponent(attachment.id)}`;
        return (
          <li key={attachment.id}>
            <a className="message-attachment" href={url} download={attachment.name} title={`${attachment.name} — Download`}>
              {PREVIEWABLE_IMAGE.test(attachment.content_type)
                ? <img className="message-attachment-preview" src={url} alt="" loading="lazy" />
                : <FileTypeIcon name={attachment.name} />}
              <span className="message-attachment-text">
                <span className="message-attachment-name">{attachment.name}</span>
                <small>
                  {formatFileSize(attachment.size)}
                  {attachment.direct && <span className="message-attachment-direct"> · Sent to model</span>}
                </small>
              </span>
            </a>
          </li>
        );
      })}
      {missing > 0 && <li className="message-attachment-missing">{missing} unavailable {missing === 1 ? "attachment" : "attachments"}</li>}
    </ul>
  );
}

function ReasoningGroup({ block, active }: { block: ReasoningBlock; active: boolean }) {
  const latest = reasoningTitle(block.parts[block.parts.length - 1]);
  return (
    <details className="work-group reasoning-group">
      <summary>
        <span className="work-chevron" aria-hidden="true"><Icon name="chevron-right" size={14} /></span>
        <span className="work-summary-content">
          <span className={active ? "activity-shimmer" : undefined}>{active ? "Thinking" : "Thought"}</span>
          {latest && <span className="work-command-preview" title={latest}>{latest}</span>}
        </span>
      </summary>
      <div className="reasoning-details">
        {block.parts.map((part, index) => (
          <MarkdownContent key={index} content={part} />
        ))}
      </div>
    </details>
  );
}

export function RunView({
  run,
  timeline,
  onApproval,
}: {
  run: Run;
  timeline: AgentEvent[];
  onApproval: (id: string, approve: boolean) => Promise<void>;
}) {
  const [clock, setClock] = useState(Date.now());
  const [pending, setPending] = useState<string | null>(null);
  const [approvalError, setApprovalError] = useState("");
  const finalStart = finalAnswerStart(timeline);
  const [activityOpen, setActivityOpen] = useState(run.status !== "completed" && finalStart === null);
  const autoClosedFor = useRef<number | null>(finalStart);
  useEffect(() => {
    if (terminal(run.status)) return;
    const timer = setInterval(() => setClock(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [run.status]);
  useLayoutEffect(() => {
    if (finalStart !== null && autoClosedFor.current !== finalStart) {
      autoClosedFor.current = finalStart;
      setActivityOpen(false);
    }
  }, [finalStart]);
  useEffect(() => {
    if (run.status === "completed" && finalStart === null) setActivityOpen(false);
    else if (["failed", "stopped"].includes(run.status)) setActivityOpen(true);
  }, [run.status, finalStart]);
  const blocks = messageBlocks(timeline, run.status);
  const activity = activityEntries(timeline, blocks, run.status, reasoningBlocks(timeline));
  const answerBlocks = blocks.filter((block) => block.final || (run.status === "completed" && !block.progress));
  const userMessage = run.request.input || "Work with attached files";
  const assistantMessage = answerBlocks.map((block) => block.content).join("\n\n");
  const approvals = timeline.filter(
    (e) =>
      e.type === "approval" &&
      !timeline.some(
        (r) =>
          r.type === "approval_resolved" && r.data.request_id === e.data.id,
      ),
  );
  const active = !terminal(run.status) && run.status !== "approval_wait" && approvals.length === 0;
  const seconds = Math.max(
    0,
    Math.round(
      ((terminal(run.status) ? Date.parse(run.updated_at) : clock) -
        Date.parse(run.created_at)) /
        1000,
    ),
  );
  async function approve(id: string, yes: boolean) {
    setPending(id);
    setApprovalError("");
    try {
      await onApproval(id, yes);
    } catch (e) {
      setApprovalError(String(e));
    } finally {
      setPending(null);
    }
  }
  return (
    <article className="turn">
      <div className="user-message-wrap">
        <RunAttachments run={run} />
        <div className="user-message">
          <p>{userMessage}</p>
        </div>
        <CopyButton content={userMessage} tooltip="Copy message" />
      </div>
      <div className="assistant-message">
        <details
          className="activity"
          open={activityOpen}
        >
          <summary onClick={(event) => {
            event.preventDefault();
            setActivityOpen((open) => !open);
          }}>
            <span className="activity-label" role={terminal(run.status) ? undefined : "status"}>
              {terminal(run.status) ? "Worked" : "Working"} for {elapsedLabel(seconds)}
            </span>
            <span className="activity-chevron" aria-hidden="true"><Icon name="chevron-right" size={15} /></span>
          </summary>
          <div className="activity-body">
            {activity.map((entry) => entry.kind === "message" ? (
              <div className="activity-message" key={entry.block.key}>
                <MarkdownContent conversationId={run.conversation_id} content={entry.block.content} />
              </div>
            ) : entry.kind === "compaction" ? (
              <CompactionNotice key={`compaction-${entry.seq}`} compaction={entry.compaction} active={active} />
            ) : entry.kind === "reasoning" ? (
              <ReasoningGroup key={`reasoning-${entry.block.key}`} block={entry.block}
                active={active && reasoningActive(entry.block, timeline, run.status)} />
            ) : (
              <WorkGroup key={entry.seq} actions={entry.actions} timeline={timeline} status={run.status} active={active} />
            ))}
          </div>
        </details>
        {!activityOpen && compactions(timeline).filter((item) => item.done).map((item) => (
          <CompactionNotice key={`compaction-summary-${item.seq}`} compaction={item} active={false} />
        ))}
        {answerBlocks.map((block) => (
          <div className="answer-block" key={block.key}><MarkdownContent conversationId={run.conversation_id} content={block.content} /></div>
        ))}
        {assistantMessage && <CopyButton content={assistantMessage} tooltip="Copy response" />}
        {terminal(run.status) && <RunChanges runId={run.id} timeline={timeline} />}
        {!terminal(run.status) &&
          approvals.map((e) => (
            <div className="approval" key={e.seq}>
              <strong>Approve external tool</strong>
              <p>
                {text(e.data.server_label)} / {text(e.data.name)}
              </p>
              <pre>{text(e.data.arguments)}</pre>
              <button
                disabled={pending !== null}
                onClick={() => void approve(text(e.data.id), true)}
              >
                Allow
              </button>
              <button
                disabled={pending !== null}
                onClick={() => void approve(text(e.data.id), false)}
              >
                Deny
              </button>
            </div>
          ))}
        {approvalError && (
          <p role="alert" className="error">
            {approvalError}
          </p>
        )}
        {timeline
          .filter((e) => e.type === "error")
          .map((e) => (
            <p role="alert" className="error" key={e.seq}>
              {text(e.data.message)}
            </p>
          ))}
      </div>
    </article>
  );
}

export function App() {
  const [config, setConfig] = useState<Config | null>(null);
  const [appSettings, setAppSettings] = useState<AppSettings>(DEFAULT_APP_SETTINGS);
  const [settingsPage, setSettingsPage] = useState<SettingsPage>("chat");
  const [costs, setCosts] = useState<CostSummary | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [query, setQuery] = useState("");
  const [searchResults, setSearchResults] = useState<Conversation[] | null>(null);
  // IME composition (Japanese input) must not search unconverted kana or romaji.
  const [searchComposing, setSearchComposing] = useState(false);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [expandedProjects, setExpandedProjects] = useState<string[]>([]);
  const [historyVisibleCounts, setHistoryVisibleCounts] = useState<Record<string, number>>({});
  const [sidebarWidth, setSidebarWidth] = useState(() => {
    const stored = Number(localStorage.getItem(SIDEBAR_WIDTH_KEY));
    return Number.isFinite(stored) && stored >= MIN_SIDEBAR_WIDTH && stored <= MAX_SIDEBAR_WIDTH
      ? stored
      : 236;
  });
  const [resizingSidebar, setResizingSidebar] = useState(false);
  const [filesWidth, setFilesWidth] = useState(() => {
    const stored = Number(localStorage.getItem(FILES_WIDTH_KEY));
    return Number.isFinite(stored) && stored >= MIN_FILES_WIDTH && stored <= MAX_FILES_WIDTH
      ? stored
      : window.innerWidth >= 1500 ? 310 : 270;
  });
  const [resizingFiles, setResizingFiles] = useState(false);
  const [pinPending, setPinPending] = useState<string[]>([]);
  const [historyRevision, setHistoryRevision] = useState(0);
  const [cid, setCid] = useState(
    localStorage.getItem("workspace-conversation") || "",
  );
  const [workspace, setWorkspace] = useState(
    localStorage.getItem(LAST_PROJECT_KEY) || "",
  );
  const [provider, setProvider] = useState("openai");
  const [model, setModel] = useState(DEFAULT_MODEL);
  const [effort, setEffort] = useState("medium");
  const [skills, setSkills] = useState<string[]>([]);
  const [resources, setResources] = useState<string[]>([]);
  const [mcps, setMcps] = useState<string[]>([]);
  const [web, setWeb] = useState(false);
  const [input, setInput] = useState("");
  const [skillMention, setSkillMention] = useState<SkillMention | null>(null);
  const [skillOption, setSkillOption] = useState(0);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [direct, setDirect] = useState<string[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [timelines, setTimelines] = useState<Record<string, AgentEvent[]>>({});
  const [filesByPath, setFilesByPath] = useState<Record<string, WorkspaceFile[]>>({});
  const [expandedFolders, setExpandedFolders] = useState<string[]>([]);
  const [loadingFolders, setLoadingFolders] = useState<string[]>([]);
  const [fileErrors, setFileErrors] = useState<Record<string, string>>({});
  const [showFiles, setShowFiles] = useState(() => window.innerWidth > 1100);
  const [terminalMounted, setTerminalMounted] = useState(false);
  const [terminalVisible, setTerminalVisible] = useState(false);
  const [terminalHeight, setTerminalHeight] = useState(() => {
    const stored = Number(localStorage.getItem(TERMINAL_HEIGHT_KEY));
    return clampTerminalHeight(stored > 0 ? stored : 300);
  });
  const [fileRevision, setFileRevision] = useState(0);
  const [error, setError] = useState("");
  const [connection, setConnection] = useState("");
  const [busy, setBusy] = useState(false);
  const [draggingFiles, setDraggingFiles] = useState(false);
  const [draggingPath, setDraggingPath] = useState(false);
  const [plusOpen, setPlusOpen] = useState(false);
  const [loadedCid, setLoadedCid] = useState("");
  const filesToggle = useRef<HTMLButtonElement>(null);
  const searchInput = useRef<HTMLInputElement>(null);
  const messageInput = useRef<HTMLTextAreaElement>(null);
  const composerBox = useRef<HTMLDivElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const fileConversation = useRef("");
  const fileRequestIds = useRef<Record<string, number>>({});
  const dragDepth = useRef(0);
  const plusWrap = useRef<HTMLDivElement>(null);
  const runSubscription = useRef<{ conversationId: string; start: (run: Run) => void } | null>(null);
  const selectedConversation = useRef(cid);
  selectedConversation.current = cid;
  const pendingSelection = useRef<number | null>(null);
  const chatContent = useRef<HTMLDivElement>(null);
  const scrollSnapshot = useRef({ top: 0, height: 0, viewport: 0 });
  const scroll = useRef<HTMLDivElement>(null);
  const follow = useRef(true);
  const current = conversations.find((c) => c.id === cid);
  const currentWorkspace = config?.workspaces.find(
    (w) => w.id === (current?.workspace_id || workspace),
  );
  const terminalAvailable = settingsPage === "chat" && Boolean(currentWorkspace);
  const activeRun = runs.find((r) => !terminal(r.status));
  const active = Boolean(activeRun);
  const selectedProvider = config?.providers.find((p) => p.id === provider);
  const configReady = Boolean(config);
  const providerModels = selectedProvider?.models || [];
  const models = providerModels.filter((item) => provider !== "azure_openai" || !current?.azure_connection_id || item.connection_id === current.azure_connection_id);
  const hasOtherConnections = provider === "azure_openai" && models.length < providerModels.length;
  const selectedModel = models.find((m) => m.id === model);
  const selectedTools = [
    ...(web ? [{ key: "web", label: "Web Search", icon: "globe" as const, remove: () => setWeb(false) }] : []),
    ...skills.map((id) => ({ key: `skill-${id}`, label: config?.skills.find((item) => item.id === id)?.label || id, icon: "spark" as const, remove: () => setSkills((old) => old.filter((value) => value !== id)) })),
    ...resources.map((id) => ({ key: `resource-${id}`, label: config?.resources.find((item) => item.id === id)?.label || id, icon: "spark" as const, remove: () => setResources((old) => old.filter((value) => value !== id)) })),
    ...mcps.map((id) => ({ key: `mcp-${id}`, label: config?.mcp_servers.find((item) => item.id === id)?.label || id, icon: "spark" as const, remove: () => setMcps((old) => old.filter((value) => value !== id)) })),
  ];
  const skillMatches = skillMention ? matchingSkills(config?.skills || [], skillMention.query) : [];
  const skillMentionOpen = Boolean(skillMention && skillMatches.length && !busy && !active);
  const activeSkillOption = Math.min(skillOption, Math.max(0, skillMatches.length - 1));
  const canSend = Boolean(
    selectedProvider?.enabled && selectedModel && cid && loadedCid === cid &&
    !busy && !active && (input.trim() || attachments.length),
  );
  const canDropFiles = Boolean(settingsPage === "chat" && cid && loadedCid === cid && !busy && !active);
  const displayedConversations = query.trim() ? searchResults || [] : conversations;
  const sortedConversations = (items: Conversation[]) => [...items].sort(
    (a, b) => b.updated_at.localeCompare(a.updated_at) || a.id.localeCompare(b.id),
  );

  useEffect(() => {
    const toggleTerminal = (event: globalThis.KeyboardEvent) => {
      if (!event.metaKey || event.ctrlKey || event.altKey || event.shiftKey || event.key.toLowerCase() !== "j") return;
      if (!terminalAvailable) return;
      event.preventDefault();
      setTerminalMounted(true);
      setTerminalVisible((visible) => !visible);
    };
    document.addEventListener("keydown", toggleTerminal);
    return () => document.removeEventListener("keydown", toggleTerminal);
  }, [terminalAvailable]);
  useEffect(() => {
    if (!terminalAvailable) setTerminalVisible(false);
  }, [terminalAvailable]);
  useEffect(() => {
    const resize = () => setTerminalHeight((value) => clampTerminalHeight(value));
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, []);

  function changeTerminalHeight(value: number) {
    const next = clampTerminalHeight(value);
    setTerminalHeight(next);
    localStorage.setItem(TERMINAL_HEIGHT_KEY, String(next));
  }

  function rememberProject(projectId: string) {
    setWorkspace(projectId);
    localStorage.setItem(LAST_PROJECT_KEY, projectId);
    setExpandedProjects((ids) => ids.includes(projectId) ? ids : [...ids, projectId]);
  }

  function selectConversation(conversation: Conversation) {
    setSettingsPage("chat");
    rememberProject(conversation.workspace_id);
    setCid(conversation.id);
  }

  async function refreshConversations() {
    setConversations(await api<Conversation[]>("/conversations"));
    setHistoryRevision((value) => value + 1);
  }
  useEffect(() => {
    if (searchComposing) return;
    const abort = new AbortController();
    setSearchResults(null);
    setSearchError("");
    if (!query.trim()) { setSearching(false); return; }
    setSearching(true);
    const timer = setTimeout(() => {
      api<Conversation[]>(`/conversations?q=${encodeURIComponent(query.trim())}`, { signal: abort.signal })
        .then((results) => { if (!abort.signal.aborted) setSearchResults(results); })
        .catch((e) => { if (!abort.signal.aborted) setSearchError(String(e)); })
        .finally(() => { if (!abort.signal.aborted) setSearching(false); });
    }, 250);
    return () => { clearTimeout(timer); abort.abort(); };
  }, [query, historyRevision, searchComposing]);

  useEffect(() => {
    if (searchOpen) searchInput.current?.focus();
  }, [searchOpen]);

  useLayoutEffect(() => {
    const element = messageInput.current;
    if (!element) return;
    const resize = () => {
      const max = Math.min(240, window.innerHeight * 0.35);
      element.style.height = "0px";
      element.style.height = `${Math.min(max, Math.max(Math.min(82, max), element.scrollHeight))}px`;
      element.style.overflowY = element.scrollHeight > max ? "auto" : "hidden";
    };
    resize();
    const observer = typeof ResizeObserver !== "undefined" ? new ResizeObserver(resize) : null;
    if (element.parentElement) observer?.observe(element.parentElement);
    window.addEventListener("resize", resize);
    return () => { observer?.disconnect(); window.removeEventListener("resize", resize); };
  }, [input, cid]);

  async function togglePin(conversation: Conversation) {
    const pinned = !conversation.pinned;
    const update = (items: Conversation[] | null, value: boolean) => items?.map((item) => item.id === conversation.id ? { ...item, pinned: value } : item) ?? null;
    setPinPending((ids) => [...ids, conversation.id]);
    setConversations((items) => update(items, pinned) || []);
    setSearchResults((items) => update(items, pinned));
    try {
      await api(`/conversations/${conversation.id}`, { method: "PATCH", body: JSON.stringify({ pinned }) });
      setHistoryRevision((value) => value + 1);
    } catch (e) {
      setConversations((items) => update(items, !pinned) || []);
      setSearchResults((items) => update(items, !pinned));
      setError(String(e));
    } finally {
      setPinPending((ids) => ids.filter((id) => id !== conversation.id));
    }
  }

  async function refreshConfig() {
    try {
      setConfig(await api<Config>("/config"));
    } catch (e) {
      setError(String(e));
    }
  }
  useEffect(() => {
    let alive = true;
    Promise.all([api<Config>("/config"), api<Conversation[]>("/conversations"), api<AppSettings>("/settings")])
      .then(([c, cs, savedSettings]) => {
        if (!alive) return;
        setConfig(c);
        setAppSettings(savedSettings);
        setConversations(cs);
        const restoredConversation = cs.find((item) => item.id === cid);
        const storedProject = localStorage.getItem(LAST_PROJECT_KEY) || "";
        const initialProject = c.workspaces.some((item) => item.id === storedProject)
          ? storedProject
          : restoredConversation?.workspace_id || c.workspaces[0]?.id || "";
        setWorkspace(initialProject);
        if (initialProject) localStorage.setItem(LAST_PROJECT_KEY, initialProject);
        setExpandedProjects(restoredConversation ? [restoredConversation.workspace_id] : []);
        const enabled = c.providers.find((p) => p.enabled && p.models.length);
        if (enabled) {
          setProvider(enabled.id);
          setModel(defaultModelId(enabled.models));
        }
        setCid(restoredConversation?.id || "");
      })
      .catch((e) => alive && setError(String(e)));
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    localStorage.setItem("workspace-conversation", cid);
    const abort = new AbortController();
    follow.current = true;
    setRuns([]);
    setTimelines({});
    setLoadedCid("");
    setConnection("");
    if (!cid || !config) return;
    const subscribed = new Set<string>();
    const disconnected = new Set<string>();
    const updateConnection = () => setConnection(disconnected.size ? "Reconnecting. The run continues on the server." : "");
    async function watch(run: Run) {
      let cursor = 0;
      while (!abort.signal.aborted) {
        try {
          await events(run.id, cursor, abort.signal, (event) => {
            if (abort.signal.aborted || event.seq <= cursor) return;
            cursor = event.seq;
            setTimelines((old) => {
              const existing = old[run.id] || [];
              if (existing.some((item) => item.seq === event.seq)) return old;
              return { ...old, [run.id]: [...existing, event] };
            });
            if (event.type === "status") {
              setRuns((old) =>
                old.map((r) =>
                  r.id === run.id
                    ? {
                        ...r,
                        status: text(event.data.status),
                        updated_at: event.created_at,
                      }
                    : r,
                ),
              );
              if (terminal(text(event.data.status)))
                setFileRevision((v) => v + 1);
            }
            if (event.type === "conversation_title") {
              const title = text(event.data.title);
              setConversations((old) => old.map((item) => item.id === run.conversation_id ? { ...item, title } : item));
              setSearchResults((old) => old?.map((item) => item.id === run.conversation_id ? { ...item, title } : item) || null);
            }
            disconnected.delete(run.id);
            updateConnection();
          });
          if (abort.signal.aborted) return;
          const latest = await api<Run>(`/runs/${run.id}`, {
            signal: abort.signal,
          });
          if (abort.signal.aborted) return;
          if (terminal(latest.status)) {
            disconnected.delete(run.id);
            updateConnection();
            setRuns((old) => old.map((r) => (r.id === run.id ? latest : r)));
            return;
          }
          throw new Error("stream disconnected");
        } catch {
          if (abort.signal.aborted) return;
          disconnected.add(run.id);
          updateConnection();
          await new Promise<void>((resolve) => {
            const finish = () => { clearTimeout(timer); abort.signal.removeEventListener("abort", finish); resolve(); };
            const timer = setTimeout(finish, 1500);
            abort.signal.addEventListener("abort", finish, { once: true });
          });
        }
      }
    }
    const subscription = {
      conversationId: cid,
      start(run: Run) {
        if (abort.signal.aborted || subscribed.has(run.id)) return;
        subscribed.add(run.id);
        void watch(run);
      },
    };
    runSubscription.current = subscription;
    api<Conversation & { runs: Run[] }>(`/conversations/${cid}`, {
      signal: abort.signal,
    })
      .then((c) => {
        if (abort.signal.aborted) return;
        setRuns(c.runs);
        setConversations((old) => old.map((item) => item.id === c.id ? { ...item, azure_connection_id: c.azure_connection_id } : item));
        setLoadedCid(cid);
        if (c.runs.length) {
          const last = c.runs[c.runs.length - 1].request;
          setProvider(last.provider);
          setModel(last.model);
          setEffort(last.reasoning_effort);
          setSkills(last.skill_ids);
          setResources(last.resource_ids);
          setMcps(last.mcp_ids);
          setWeb(last.web_search);
        }
        for (const run of c.runs) subscription.start(run);
      })
      .catch((e) => {
        if (!abort.signal.aborted) setError(String(e));
      });
    return () => {
      abort.abort();
      if (runSubscription.current === subscription) runSubscription.current = null;
    };
  }, [cid, configReady]);

  useEffect(() => {
    setFilesByPath({});
    setExpandedFolders([]);
    setLoadingFolders([]);
    setFileErrors({});
    setAttachments([]);
    setDirect([]);
    setInput("");
    setSkillMention(null);
    setPlusOpen(false);
    setError("");
    follow.current = true;
  }, [cid]);

  async function loadFileFolder(path: string, conversationId = cid) {
    if (!conversationId) return;
    const requestId = (fileRequestIds.current[path] || 0) + 1;
    fileRequestIds.current[path] = requestId;
    setLoadingFolders((items) => items.includes(path) ? items : [...items, path]);
    setFileErrors((items) => {
      const next = { ...items };
      delete next[path];
      return next;
    });
    try {
      const entries = await api<WorkspaceFile[]>(`/conversations/${conversationId}/files?path=${encodeURIComponent(path)}`);
      if (fileConversation.current !== conversationId || fileRequestIds.current[path] !== requestId) return;
      setFilesByPath((items) => ({ ...items, [path]: entries }));
    } catch (e) {
      if (fileConversation.current !== conversationId || fileRequestIds.current[path] !== requestId) return;
      setFileErrors((items) => ({ ...items, [path]: String(e) }));
    } finally {
      if (fileConversation.current === conversationId && fileRequestIds.current[path] === requestId)
        setLoadingFolders((items) => items.filter((item) => item !== path));
    }
  }

  function toggleFileFolder(entry: WorkspaceFile) {
    if (expandedFolders.includes(entry.path)) {
      setExpandedFolders((items) => items.filter((path) => path !== entry.path));
      return;
    }
    setExpandedFolders((items) => [...items, entry.path]);
    if (!(entry.path in filesByPath) && !loadingFolders.includes(entry.path)) void loadFileFolder(entry.path);
  }

  useEffect(() => {
    if (!cid) {
      fileConversation.current = "";
      setFilesByPath({});
      return;
    }
    const changedConversation = fileConversation.current !== cid;
    fileConversation.current = cid;
    const paths = changedConversation ? [""] : ["", ...expandedFolders];
    for (const path of paths) void loadFileFolder(path, cid);
  }, [cid, fileRevision]);
  function followLatest() {
    const element = scroll.current;
    if (!element) return;
    if (follow.current) element.scrollTop = Math.max(0, element.scrollHeight - element.clientHeight);
    scrollSnapshot.current = { top: element.scrollTop, height: element.scrollHeight, viewport: element.clientHeight };
  }
  useLayoutEffect(() => {
    if (pendingSelection.current !== null && messageInput.current) {
      messageInput.current.focus({ preventScroll: true });
      messageInput.current.setSelectionRange(pendingSelection.current, pendingSelection.current);
      pendingSelection.current = null;
    }
    followLatest();
  });
  useLayoutEffect(() => {
    const observer = typeof ResizeObserver !== "undefined" ? new ResizeObserver(followLatest) : null;
    if (scroll.current) observer?.observe(scroll.current);
    if (chatContent.current) observer?.observe(chatContent.current);
    return () => observer?.disconnect();
  }, [cid, settingsPage]);
  useEffect(() => {
    if (!plusOpen) return;
    const closeOutside = (event: PointerEvent) => {
      if (!plusWrap.current?.contains(event.target as Node)) setPlusOpen(false);
    };
    document.addEventListener("pointerdown", closeOutside);
    return () => document.removeEventListener("pointerdown", closeOutside);
  }, [plusOpen]);
  useEffect(() => {
    if (!skillMentionOpen) return;
    const closeOutside = (event: PointerEvent) => {
      if (!composerBox.current?.contains(event.target as Node)) setSkillMention(null);
    };
    document.addEventListener("pointerdown", closeOutside);
    return () => document.removeEventListener("pointerdown", closeOutside);
  }, [skillMentionOpen]);
  useEffect(() => {
    if (canDropFiles) return;
    dragDepth.current = 0;
    setDraggingFiles(false);
    setDraggingPath(false);
  }, [canDropFiles]);
  useEffect(() => {
    if (settingsPage !== "cost") return;
    api<CostSummary>("/costs/monthly").then(setCosts).catch((e) => setError(String(e)));
  }, [settingsPage]);
  useEffect(() => {
    const preventFileNavigation = (event: globalThis.DragEvent) => {
      if (Array.from(event.dataTransfer?.types || []).includes("Files"))
        event.preventDefault();
    };
    window.addEventListener("dragover", preventFileNavigation);
    window.addEventListener("drop", preventFileNavigation);
    return () => {
      window.removeEventListener("dragover", preventFileNavigation);
      window.removeEventListener("drop", preventFileNavigation);
    };
  }, []);

  async function newConversation(projectId = workspace) {
    if (!projectId) return;
    setBusy(true);
    setError("");
    try {
      setSettingsPage("chat");
      const c = await api<Conversation>("/conversations", {
        method: "POST",
        body: JSON.stringify({ workspace_id: projectId }),
      });
      await refreshConversations();
      rememberProject(projectId);
      setCid(c.id);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  async function saveAppSettings(changes: Partial<AppSettings>) {
    const previous = appSettings;
    const optimistic = { ...appSettings, ...changes };
    setAppSettings(optimistic);
    try {
      const saved = await api<AppSettings>("/settings", {
        method: "PATCH",
        body: JSON.stringify(changes),
      });
      setAppSettings(saved);
    } catch (e) {
      setAppSettings(previous);
      setError(String(e));
    }
  }
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!canSend) return;
    setError("");
    setBusy(true);
    const submittingCid = cid;
    const subscription = runSubscription.current;
    try {
      const createdRun = await api<Run>("/runs", {
        method: "POST",
        body: JSON.stringify({
          conversation_id: cid,
          provider,
          model,
          reasoning_effort: effort,
          input,
          attachment_ids: attachments.map((a) => a.id),
          direct_attachment_ids: direct,
          skill_ids: skills,
          resource_ids: resources,
          mcp_ids: mcps,
          web_search: web,
        }),
      });
      if (selectedConversation.current !== submittingCid || runSubscription.current !== subscription) return;
      follow.current = true;
      setRuns((old) => old.some((run) => run.id === createdRun.id) ? old : [...old, createdRun]);
      if (provider === "azure_openai" && selectedModel?.connection_id) {
        setConversations((old) => old.map((item) => item.id === submittingCid ? { ...item, azure_connection_id: selectedModel.connection_id } : item));
      }
      subscription?.start(createdRun);
      setInput("");
      setSkillMention(null);
      setAttachments([]);
      setDirect([]);
      await refreshConversations();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  function updateSkillMention(value: string, cursor: number | null) {
    const mention = config?.skills.length && cursor !== null
      ? findSkillMention(value, cursor)
      : null;
    setSkillMention(mention || null);
    setSkillOption(0);
    if (mention) setPlusOpen(false);
  }
  function selectSkillMention(skillId: string) {
    if (!skillMention) return;
    const skill = config?.skills.find((item) => item.id === skillId);
    if (!skill) return;
    const replacement = replaceSkillMention(input, skillMention);
    setInput(replacement.value);
    setSkills((old) => old.includes(skill.id) ? old : [...old, skill.id]);
    setSkillMention(null);
    window.setTimeout(() => {
      messageInput.current?.focus();
      messageInput.current?.setSelectionRange(replacement.cursor, replacement.cursor);
    }, 0);
  }
  function handleComposerKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.nativeEvent.isComposing || e.keyCode === 229) return;
    if (skillMentionOpen) {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        const direction = e.key === "ArrowDown" ? 1 : -1;
        setSkillOption((activeSkillOption + direction + skillMatches.length) % skillMatches.length);
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        setSkillMention(null);
        return;
      }
      if ((e.key === "Enter" && !e.shiftKey) || e.key === "Tab") {
        e.preventDefault();
        selectSkillMention(skillMatches[activeSkillOption].id);
        return;
      }
      if ((e.key === " " || e.key === "Spacebar") && skillMention) {
        const exact = exactSkillMatch(skillMatches, skillMention.query);
        if (exact) {
          e.preventDefault();
          selectSkillMention(exact.id);
          return;
        }
      }
    }
    if (e.key !== "Enter" || e.shiftKey) return;
    e.preventDefault();
    if (canSend) e.currentTarget.form?.requestSubmit();
  }
  async function stopRun() {
    if (!activeRun) return;
    try {
      await api(`/runs/${activeRun.id}/stop`, { method: "POST" });
    } catch (e) {
      setError(String(e));
    }
  }
  async function upload(selected: FileList | readonly File[] | null) {
    if (!selected?.length || !canDropFiles) return;
    setBusy(true);
    setError("");
    try {
      const body = new FormData();
      body.append("conversation_id", cid);
      Array.from(selected).forEach((f) => body.append("files", f));
      const added = await api<Attachment[]>("/attachments", {
        method: "POST",
        body,
      });
      setAttachments((old) => [...old, ...added]);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  function isWorkspaceFileDrag(event: ReactDragEvent<HTMLElement>) {
    return Array.from(event.dataTransfer.types).includes(WORKSPACE_FILE_MIME);
  }
  function handlePathDrop(event: ReactDragEvent<HTMLTextAreaElement>) {
    if (!isWorkspaceFileDrag(event)) return;
    event.preventDefault();
    event.stopPropagation();
    setDraggingPath(false);
    if (!canDropFiles) return;
    try {
      const data = JSON.parse(event.dataTransfer.getData(WORKSPACE_FILE_MIME));
      if (data.conversationId !== cid || typeof data.path !== "string" || !data.path || data.path.startsWith("/") || data.path.split("/").some((part: string) => part === "..")) return;
      const { selectionStart: start, selectionEnd: end } = event.currentTarget;
      pendingSelection.current = start + data.path.length;
      setInput(input.slice(0, start) + data.path + input.slice(end));
      setSkillMention(null);
    } catch { /* Ignore unsupported drag data. */ }
  }
  function isFileDrag(event: ReactDragEvent<HTMLElement>) {
    return Array.from(event.dataTransfer.types).includes("Files");
  }
  function droppedFiles(event: ReactDragEvent<HTMLElement>) {
    const items = Array.from(event.dataTransfer.items || []);
    if (!items.length) return Array.from(event.dataTransfer.files);
    return items.flatMap((item) => {
      if (item.kind !== "file") return [];
      const entry = (
        item as DataTransferItem & {
          webkitGetAsEntry?: () => { isDirectory: boolean } | null;
        }
      ).webkitGetAsEntry?.();
      const file = item.getAsFile();
      return file && !entry?.isDirectory ? [file] : [];
    });
  }
  function handleDragEnter(event: ReactDragEvent<HTMLElement>) {
    if (!isFileDrag(event)) return;
    event.preventDefault();
    event.stopPropagation();
    if (!canDropFiles) return;
    dragDepth.current += 1;
    setDraggingFiles(true);
  }
  function handleDragOver(event: ReactDragEvent<HTMLElement>) {
    if (isWorkspaceFileDrag(event)) {
      event.preventDefault();
      event.dataTransfer.dropEffect = "none";
      return;
    }
    if (!isFileDrag(event)) return;
    event.preventDefault();
    event.stopPropagation();
    event.dataTransfer.dropEffect = canDropFiles ? "copy" : "none";
  }
  function handleDragLeave(event: ReactDragEvent<HTMLElement>) {
    if (!isFileDrag(event)) return;
    event.preventDefault();
    event.stopPropagation();
    dragDepth.current = Math.max(0, dragDepth.current - 1);
    if (dragDepth.current === 0) setDraggingFiles(false);
  }
  function handleDrop(event: ReactDragEvent<HTMLElement>) {
    if (isWorkspaceFileDrag(event)) { event.preventDefault(); return; }
    if (!isFileDrag(event)) return;
    event.preventDefault();
    event.stopPropagation();
    dragDepth.current = 0;
    setDraggingFiles(false);
    if (!canDropFiles) return;
    void upload(droppedFiles(event));
  }
  async function removeConversation(id: string) {
    try {
      await api(`/conversations/${id}`, { method: "DELETE" });
      await refreshConversations();
      if (cid === id) setCid("");
    } catch (e) {
      setError(String(e));
    }
  }

  function toggleSearch() {
    setSearchOpen((open) => {
      if (open) {
        setQuery("");
        setSearchResults(null);
        setSearchError("");
      }
      return !open;
    });
  }

  function toggleProject(projectId: string) {
    setExpandedProjects((ids) => ids.includes(projectId)
      ? ids.filter((id) => id !== projectId)
      : [...ids, projectId]);
  }

  function updateSidebarWidth(clientX: number) {
    const next = Math.min(MAX_SIDEBAR_WIDTH, Math.max(MIN_SIDEBAR_WIDTH, Math.round(clientX)));
    setSidebarWidth(next);
    localStorage.setItem(SIDEBAR_WIDTH_KEY, String(next));
  }

  function updateFilesWidth(value: number) {
    const desktopLimit = window.innerWidth > 1100
      ? window.innerWidth - sidebarWidth - 420
      : window.innerWidth - 180;
    const maximum = Math.max(MIN_FILES_WIDTH, Math.min(MAX_FILES_WIDTH, desktopLimit));
    const next = Math.min(maximum, Math.max(MIN_FILES_WIDTH, Math.round(value)));
    setFilesWidth(next);
    localStorage.setItem(FILES_WIDTH_KEY, String(next));
  }

  function conversationRow(conversation: Conversation, nested = false) {
    return (
      <div className={`conversation ${nested ? "nested" : ""} ${conversation.id === cid ? "selected" : ""}`} key={conversation.id}>
        <button className="history-title" disabled={busy} onClick={() => selectConversation(conversation)}>{conversation.title}</button>
        <button className="history-action pin" title={conversation.pinned ? "Unpin chat" : "Pin chat"} aria-label={`${conversation.pinned ? "Unpin" : "Pin"} ${conversation.title}`} aria-pressed={Boolean(conversation.pinned)} disabled={pinPending.includes(conversation.id)} onClick={() => void togglePin(conversation)}><Icon name="pin" size={14} /></button>
        <button className="history-action delete" title="Delete chat" aria-label={`Delete ${conversation.title}`} disabled={busy || pinPending.includes(conversation.id) || (conversation.id === cid && active)} onClick={() => void removeConversation(conversation.id)}><Icon name="close" size={14} /></button>
      </div>
    );
  }

  function showMoreHistory(projectId: string) {
    setHistoryVisibleCounts((counts) => ({
      ...counts,
      [projectId]: (counts[projectId] || HISTORY_INITIAL_COUNT) + HISTORY_PAGE_SIZE,
    }));
  }

  return (
    <div
      className={`app-shell ${showFiles && settingsPage === "chat" ? "with-files" : "without-files"} ${terminalVisible ? "has-terminal" : ""} ${resizingSidebar ? "is-resizing-sidebar" : ""} ${resizingFiles ? "is-resizing-files" : ""}`}
      style={{ "--sidebar-width": `${sidebarWidth}px`, "--files-width": `${filesWidth}px`, "--terminal-height": `${terminalHeight}px`, ...themeVariables(appSettings.theme_color) } as CSSProperties}
    >
      {terminalAvailable && <button
        className="panel-toggle terminal-toggle"
        type="button"
        aria-label={terminalVisible ? "Hide host terminal" : "Show host terminal"}
        title={`${terminalVisible ? "Hide" : "Show"} host terminal (⌘J)`}
        aria-keyshortcuts="Meta+J"
        aria-controls="host-terminal-panel"
        aria-expanded={terminalVisible}
        onClick={() => {
          setTerminalMounted(true);
          setTerminalVisible((visible) => !visible);
        }}
      >
        <Icon name="terminal" size={20} />
      </button>}
      {settingsPage === "chat" && <button
        ref={filesToggle}
        className="panel-toggle"
        type="button"
        aria-label={showFiles ? "Hide files panel" : "Show files panel"}
        title={showFiles ? "Hide files panel" : "Show files panel"}
        aria-controls="files-panel"
        aria-expanded={showFiles}
        onClick={() => setShowFiles((value) => !value)}
        onKeyDown={(event) => { if (event.key === "Escape") setShowFiles(false); }}
      >
        <Icon name="panel-right" size={20} />
      </button>}
      <aside className="sidebar">
        <a className="brand" href="/">
          <img className="brand-icon" src="/app-icon.png" alt="" />
          <span>
            Workspace<span className="brand-sub">RESPONSES AGENT</span>
          </span>
        </a>
        <div className="sidebar-commands">
          <button className="sidebar-command" disabled={!workspace || busy} onClick={() => void newConversation()}>
            <Icon name="compose" size={19} />
            <span>New chat</span>
          </button>
          {searchOpen ? (
            <div className="sidebar-search-field" id="sidebar-search" role="search">
              <Icon name="search" size={19} />
              <input
                ref={searchInput}
                className="history-search"
                type="search"
                aria-label="Search history"
                placeholder="Search chats"
                title='Separate words with spaces to match all of them; use "quotes" for a phrase'
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                onCompositionStart={() => setSearchComposing(true)}
                onCompositionEnd={(event) => {
                  setQuery(event.currentTarget.value);
                  setSearchComposing(false);
                }}
                onKeyDown={(event) => {
                  if (event.key === "Escape" && !event.nativeEvent.isComposing) toggleSearch();
                }}
              />
              <button className="sidebar-search-close" type="button" aria-label="Close search" title="Close search" onClick={toggleSearch}>
                <Icon name="close" size={15} />
              </button>
            </div>
          ) : (
            <button className="sidebar-command" aria-expanded="false" aria-controls="sidebar-search" onClick={toggleSearch}>
              <Icon name="search" size={19} />
              <span>Search</span>
            </button>
          )}
        </div>
        {searchOpen && (searching || searchError) && (
          <div className="search-feedback">
            {searching && <small role="status">Searching…</small>}
            {searchError && <small role="alert">{searchError}</small>}
          </div>
        )}
        <nav aria-label="History">
          {sortedConversations(displayedConversations.filter((conversation) => conversation.pinned)).length > 0 && (
            <section className="history-group" aria-labelledby="pinned-heading">
              <h2 className="sidebar-heading" id="pinned-heading">Pinned</h2>
              {sortedConversations(displayedConversations.filter((conversation) => conversation.pinned)).map((conversation) => conversationRow(conversation))}
            </section>
          )}
          <section className="projects-section" aria-labelledby="projects-heading">
            <h2 className="sidebar-heading" id="projects-heading">Projects</h2>
            {config?.workspaces.map((project) => {
              const items = sortedConversations(displayedConversations.filter((conversation) => conversation.workspace_id === project.id));
              if (query.trim() && items.length === 0) return null;
              const expanded = query.trim() ? items.length > 0 : expandedProjects.includes(project.id);
              const regularItems = items.filter((conversation) => !conversation.pinned);
              const visibleCount = historyVisibleCounts[project.id] || HISTORY_INITIAL_COUNT;
              const visibleRegularIds = new Set(regularItems.slice(0, visibleCount).map((conversation) => conversation.id));
              const visibleItems = query.trim()
                ? items
                : items.filter((conversation) => conversation.pinned || visibleRegularIds.has(conversation.id));
              const hasMoreHistory = !query.trim() && regularItems.length > visibleCount;
              return (
                <div className={`project-group ${expanded ? "is-expanded" : ""}`} key={project.id}>
                  <div className="project-row">
                    <button className="project-toggle" type="button" aria-expanded={expanded} aria-label={`${expanded ? "Collapse" : "Expand"} ${project.label}`} onClick={() => toggleProject(project.id)}>
                      <Icon name={expanded ? "folder-open" : "folder"} size={18} />
                      <span>{project.label}</span>
                    </button>
                    <button className="project-new" type="button" aria-label={`New chat in ${project.label}`} title={`New chat in ${project.label}`} disabled={busy} onClick={() => void newConversation(project.id)}>
                      <Icon name="compose" size={16} />
                    </button>
                  </div>
                  <div className={`project-conversations ${expanded ? "is-expanded" : ""}`} aria-hidden={!expanded}>
                    <div className="project-conversations-inner">
                      {visibleItems.map((conversation) => conversationRow(conversation, true))}
                      {hasMoreHistory && (
                        <button className="history-more" type="button" onClick={() => showMoreHistory(project.id)}>
                          Show more
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </section>
          {query.trim() && !searching && !searchError && searchResults?.length === 0 && <p className="muted">No matching conversations</p>}
        </nav>
        <button className="sidebar-settings" type="button" aria-current={settingsPage !== "chat" ? "page" : undefined} onClick={() => setSettingsPage("settings")}>
          <Icon name="gear" size={18} />
          <span>Settings</span>
        </button>
        <div
          className="sidebar-resizer"
          role="separator"
          aria-label="Resize sidebar"
          aria-orientation="vertical"
          aria-valuemin={MIN_SIDEBAR_WIDTH}
          aria-valuemax={MAX_SIDEBAR_WIDTH}
          aria-valuenow={sidebarWidth}
          tabIndex={0}
          onPointerDown={(event) => {
            if (event.button !== 0) return;
            event.currentTarget.setPointerCapture(event.pointerId);
            setResizingSidebar(true);
          }}
          onPointerMove={(event) => {
            if (resizingSidebar && event.currentTarget.hasPointerCapture(event.pointerId)) updateSidebarWidth(event.clientX);
          }}
          onPointerUp={(event) => {
            if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
            setResizingSidebar(false);
          }}
          onPointerCancel={() => setResizingSidebar(false)}
          onKeyDown={(event) => {
            if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
            event.preventDefault();
            updateSidebarWidth(sidebarWidth + (event.key === "ArrowRight" ? 10 : -10));
          }}
        />
      </aside>
      <main
        className={`main ${draggingFiles ? "is-file-dragging" : ""}`}
        onDragEnter={handleDragEnter}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        {settingsPage !== "chat" ? (
          <SettingsPanel page={settingsPage} config={config} settings={appSettings} costs={costs} onNavigate={setSettingsPage} onChange={saveAppSettings} />
        ) : <>
        {cid && (
          <header className="chat-header">
            <Icon name="folder" size={17} />
            <h1 title={current?.title || "New chat"}>{current?.title || "New chat"}</h1>
          </header>
        )}
        {draggingFiles && (
          <div className="file-drop-overlay" role="status" aria-live="polite">
            <Icon name="paperclip" size={28} />
            <strong>Drop files to attach</strong>
          </div>
        )}

        <div
          className="chat-scroll"
          ref={scroll}
          onWheel={(event) => { if (event.deltaY < 0) follow.current = false; }}
          onScroll={() => {
            const el = scroll.current;
            if (!el) return;
            const previous = scrollSnapshot.current;
            const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 2;
            if (nearBottom) follow.current = true;
            else if (el.scrollTop < previous.top && el.scrollHeight === previous.height && el.clientHeight === previous.viewport) follow.current = false;
            scrollSnapshot.current = { top: el.scrollTop, height: el.scrollHeight, viewport: el.clientHeight };
          }}
        >
          {!cid ? (
            <div className="welcome">
              <img className="welcome-icon" src="/app-icon.png" alt="" />
              <h2>Explore, analyze, create.</h2>
              <p>
                Choose a project or start a new chat in your most recent project.
                <br />
                Ask the agent to inspect, edit, and check your files.
              </p>
              {!config?.workspaces.length && (
                <p className="setup-note">
                  Copy runtime.example.toml to runtime.toml and set an absolute
                  workspace path.
                </p>
              )}
              <div className="examples">
                <span>Compare papers in a research folder</span>
                <span>Analyze a CSV and save a chart</span>
                <span>Review and edit a Word or Excel file</span>
              </div>
            </div>
          ) : (
            <div className="chat-column" ref={chatContent}>
              {runs.length === 0 && (
                <div className="welcome compact">
                  <h2>What would you like to work on?</h2>
                  <p>Describe the files and the result you want.</p>
                </div>
              )}
              {runs.map((run) => (
                <RunView
                  key={run.id}
                  run={run}
                  timeline={timelines[run.id] || []}
                  onApproval={async (id, approve) => {
                    await api(`/runs/${run.id}/approvals`, {
                      method: "POST",
                      body: JSON.stringify({ request_id: id, approve }),
                    });
                  }}
                />
              ))}
            </div>
          )}
        </div>
        {cid && (
          <form className="composer" onSubmit={submit}>
            {connection && (
              <p className="connection" role="status">
                {connection}
              </p>
            )}
            <div className={`composer-box ${draggingPath ? "is-path-dragging" : ""}`} ref={composerBox}>
              <div className="attachments">
                {attachments.map((a) => (
                  <div className="attachment" key={a.id}>
                    <FileTypeIcon name={a.name} />
                    <span className="attachment-name" title={a.name}>{a.name}</span>
                    <small className="attachment-size">{formatFileSize(a.size)}</small>
                    {/\.(pdf|png|jpe?g|webp)$/i.test(a.name) && (
                      <label>
                        <input
                          type="checkbox"
                          checked={direct.includes(a.id)}
                          onChange={(e) =>
                            setDirect((old) =>
                              e.target.checked
                                ? [...old, a.id]
                                : old.filter((id) => id !== a.id),
                            )
                          }
                        />
                        Send directly to model
                      </label>
                    )}
                    <button
                      type="button"
                      aria-label={`Remove ${a.name}`}
                      onClick={() => {
                        setAttachments((old) => old.filter((f) => f.id !== a.id));
                        setDirect((old) => old.filter((id) => id !== a.id));
                      }}
                    >
                      <Icon name="close" size={13} />
                    </button>
                  </div>
                ))}
              </div>
              <textarea
                ref={messageInput}
                onDragEnter={(event) => {
                  if (!isWorkspaceFileDrag(event)) return;
                  event.preventDefault();
                  event.stopPropagation();
                  setDraggingPath(canDropFiles);
                }}
                onDragOver={(event) => {
                  if (!isWorkspaceFileDrag(event)) return;
                  event.preventDefault();
                  event.stopPropagation();
                  event.dataTransfer.dropEffect = canDropFiles ? "copy" : "none";
                }}
                onDragLeave={() => setDraggingPath(false)}
                onDrop={handlePathDrop}
                aria-label="Message"
                aria-autocomplete="list"
                aria-controls={skillMentionOpen ? "skill-mention-list" : undefined}
                aria-expanded={skillMentionOpen}
                aria-activedescendant={skillMentionOpen ? `skill-mention-${skillMatches[activeSkillOption].id}` : undefined}
                placeholder="Ask anything"
                value={input}
                onChange={(e) => {
                  setInput(e.target.value);
                  updateSkillMention(e.target.value, e.target.selectionStart);
                }}
                onSelect={(e) => updateSkillMention(e.currentTarget.value, e.currentTarget.selectionStart)}
                onKeyDown={handleComposerKeyDown}
                disabled={busy || active}
                rows={3}
              />
              {draggingPath && <span className="path-drop-hint" role="status">Drop to insert relative path</span>}
              {skillMentionOpen && (
                <div className="skill-mention-menu" id="skill-mention-list" role="listbox" aria-label="Skills">
                  {skillMatches.map((skill, index) => (
                    <button
                      className={index === activeSkillOption ? "is-active" : ""}
                      id={`skill-mention-${skill.id}`}
                      key={skill.id}
                      type="button"
                      role="option"
                      aria-selected={index === activeSkillOption}
                      onMouseDown={(event) => event.preventDefault()}
                      onClick={() => selectSkillMention(skill.id)}
                    >
                      <Icon name="spark" size={16} />
                      <span>
                        <strong>@{skillMentionName(skill)}</strong>
                        {skill.label !== skillMentionName(skill) && <small>{skill.label}</small>}
                        <small>{skill.description}</small>
                      </span>
                      {skills.includes(skill.id) && <Icon name="check" size={16} />}
                    </button>
                  ))}
                </div>
              )}
              <div className="composer-actions">
                <div className="plus-wrap" ref={plusWrap}>
                  <button
                    className="plus-button"
                    type="button"
                    aria-label="Add attachments and tools"
                    aria-expanded={plusOpen}
                    onClick={() => {
                      setSkillMention(null);
                      setPlusOpen((v) => !v);
                      if (!plusOpen) void refreshConfig();
                    }}
                    disabled={active || busy}
                  >
                    <Icon name="plus" size={18} />
                  </button>
                  {plusOpen && (
                    <div className="plus-menu" aria-label="Attachments and tools" onKeyDown={(e) => {
                      if (e.key === "Escape") setPlusOpen(false);
                    }}>
                      <button className="tool-option attach-option" type="button" onClick={() => fileInput.current?.click()}>
                        <Icon name="paperclip" />
                        <span>Attach files</span>
                      </button>
                      <button className={`tool-option ${web ? "is-selected" : ""}`} type="button" aria-pressed={web} onClick={() => setWeb((value) => !value)}>
                        <Icon name="globe" />
                        <span>Web Search</span>
                        {web && <Icon name="check" size={16} />}
                      </button>
                      <Choices
                        label="Skills"
                        items={config?.skills || []}
                        selected={skills}
                        change={setSkills}
                        disabled={active}
                      />
                      <Choices
                        label="Resources"
                        items={config?.resources || []}
                        selected={resources}
                        change={setResources}
                        disabled={active}
                      />
                      <Choices
                        label="Remote MCP"
                        items={config?.mcp_servers || []}
                        selected={mcps}
                        change={setMcps}
                        disabled={active}
                      />
                      <label className="provider-choice">
                        Provider
                        <select
                          aria-label="Provider"
                          value={provider}
                          disabled={active || runs.length > 0}
                          onChange={(e) => {
                            setProvider(e.target.value);
                            setModel(defaultModelId(
                              config?.providers.find((p) => p.id === e.target.value)?.models ?? [],
                            ));
                            setEffort("medium");
                          }}
                        >
                          {config?.providers.map((p) => (
                            <option key={p.id} value={p.id} disabled={!p.enabled}>
                              {p.label}
                              {!p.enabled ? " (unavailable)" : ""}
                            </option>
                          ))}
                        </select>
                      </label>
                    </div>
                  )}
                </div>
                {selectedTools.length > 0 && (
                  <div className="selected-tools" aria-label="Selected tools">
                    {selectedTools.map((tool) => (
                      <span className="selected-tool" key={tool.key}>
                        <Icon name={tool.icon} size={14} />
                        <span>{tool.label}</span>
                        <button type="button" aria-label={`Remove ${tool.label}`} title={`Remove ${tool.label}`} disabled={active || busy} onClick={tool.remove}>
                          <Icon name="close" size={13} />
                        </button>
                      </span>
                    ))}
                  </div>
                )}
                <input
                  ref={fileInput}
                  className="visually-hidden"
                  type="file"
                  multiple
                  disabled={!cid || busy || active}
                  onChange={(e) => {
                    void upload(e.target.files);
                    e.target.value = "";
                    setPlusOpen(false);
                  }}
                />
                <div className="composer-selection">
                  {(() => {
                    const { primary, more } = splitModelsByFamily(models);
                    const toOption = (m: Model) => ({ value: m.id, label: modelDisplayLabel(m), icon: modelFamilyIconName(m.model) });
                    return (
                      <PopoverSelect
                        label="Model"
                        value={model}
                        disabled={active}
                        className="model-select"
                        options={primary.map(toOption)}
                        moreOptions={more.map(toOption)}
                        moreLabel="More models"
                        onChange={(value) => {
                          setModel(value);
                          setEffort("medium");
                        }}
                      />
                    );
                  })()}
                  <EffortSlider
                    value={effort}
                    levels={selectedModel?.efforts || []}
                    disabled={active}
                    onChange={setEffort}
                  />
                </div>
                {(() => {
                  const usage = contextUsage(runs.map((run) => timelines[run.id] || []));
                  return usage && config?.compact_token_threshold ? (
                    <ContextRing tokens={usage.tokens} compacted={usage.compacted} compacting={usage.compacting}
                      threshold={config.compact_token_threshold} modelLimit={selectedModel?.max_input_tokens} />
                  ) : null;
                })()}
                {activeRun ? (
                  <button
                    className="send stop-send"
                    type="button"
                    aria-label="Stop"
                    onClick={() => void stopRun()}
                  >
                    <span className="stop-square" />
                  </button>
                ) : (
                  <button
                    className="send"
                    type="submit"
                    aria-label="Send"
                    disabled={!canSend}
                  >
                    <Icon name="arrow-up" size={18} />
                  </button>
                )}
              </div>
            </div>
            {hasOtherConnections && <p className="composer-note">別接続先のモデルは新規チャットで選択してください。</p>}
            <p className="composer-note">Sandboxed: network access is disabled; only files in the mounted workspace can be modified.</p>
          </form>
        )}
        </>}
        {error && (
          <div className="error-banner" role="alert">
            {error}
            <button aria-label="Dismiss error" onClick={() => setError("")}>
              <Icon name="close" size={14} />
            </button>
          </div>
        )}
      </main>
      {settingsPage === "chat" && <aside
        id="files-panel"
        aria-label="Files"
        className={`files-panel ${showFiles ? "is-open" : ""}`}
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            setShowFiles(false);
            filesToggle.current?.focus();
          }
        }}
      >
        <div
          className="files-resizer"
          role="separator"
          aria-label="Resize files panel"
          aria-orientation="vertical"
          aria-valuemin={MIN_FILES_WIDTH}
          aria-valuemax={MAX_FILES_WIDTH}
          aria-valuenow={filesWidth}
          tabIndex={0}
          onPointerDown={(event) => {
            if (event.button !== 0) return;
            event.currentTarget.setPointerCapture(event.pointerId);
            setResizingFiles(true);
          }}
          onPointerMove={(event) => {
            if (event.currentTarget.hasPointerCapture(event.pointerId)) updateFilesWidth(window.innerWidth - event.clientX);
          }}
          onPointerUp={(event) => {
            if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
            setResizingFiles(false);
          }}
          onPointerCancel={() => setResizingFiles(false)}
          onKeyDown={(event) => {
            if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
            event.preventDefault();
            updateFilesWidth(filesWidth + (event.key === "ArrowLeft" ? 10 : -10));
          }}
        />
        <div className="files-header">
          <h2>Files</h2>
          <button className={`refresh-files ${loadingFolders.includes("") ? "is-loading" : ""}`} type="button" aria-label="Refresh files" title="Refresh files" disabled={!cid || loadingFolders.includes("")} onClick={() => setFileRevision((v) => v + 1)}>
            <Icon name="refresh" size={17} />
          </button>
        </div>
        <p className="workspace-path">
          {currentWorkspace?.path || "No workspace selected"}
        </p>
        <div className="folder-path"><Icon name="folder-open" size={15} /><span>/workspace</span></div>
        <div className="file-list">
          {loadingFolders.includes("") && !filesByPath[""] && <div className="file-tree-state file-tree-root-state" role="status"><span className="file-tree-spinner" />Loading files…</div>}
          {!loadingFolders.includes("") && fileErrors[""] && <div className="file-tree-state file-tree-error file-tree-root-state" role="alert"><span>Couldn’t load files.</span><button type="button" onClick={() => void loadFileFolder("")}>Retry</button></div>}
          {!loadingFolders.includes("") && !fileErrors[""] && filesByPath[""]?.length === 0 && <div className="file-tree-state file-tree-root-state">No files yet</div>}
          {filesByPath[""] && <FileTree entries={filesByPath[""]} childrenByPath={filesByPath} expanded={expandedFolders} loading={loadingFolders} errors={fileErrors} onToggle={toggleFileFolder} onRetry={(path) => void loadFileFolder(path)} conversationId={cid} />}
        </div>
        <p className="files-note">
          Drag a file or folder to the message input to insert its relative path.
        </p>
      </aside>}
      {terminalMounted && currentWorkspace && <div id="host-terminal-panel"
        className={`terminal-grid-cell ${terminalVisible ? "" : "is-hidden"}`}
        aria-hidden={!terminalVisible}>
        <Suspense fallback={<div className="terminal-loading">Opening host terminal…</div>}>
          <HostTerminalPanel
            currentWorkspaceId={currentWorkspace.id}
            currentWorkspacePath={currentWorkspace.path}
            visible={terminalVisible}
            height={terminalHeight}
            onHeightChange={changeTerminalHeight}
            onClose={() => { setTerminalVisible(false); setFileRevision((value) => value + 1); }}
          />
        </Suspense>
      </div>}
    </div>
  );
}
