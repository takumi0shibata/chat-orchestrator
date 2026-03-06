import { ChangeEvent, FormEvent, useEffect, useMemo, useRef, useState } from "react";

import type { ModelInfo, SkillInfo } from "../types";
import {
  AttachmentIcon,
  CheckIcon,
  ChevronDownIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  SendIcon,
  SettingsIcon,
  StopIcon
} from "./Icons";

type Attachment = {
  id: string;
  name: string;
  content: string;
};

type RichModel = ModelInfo & {
  providerId: string;
  providerLabel: string;
  providerEnabled: boolean;
};

type ComposerMenu = "model" | "skill" | "settings" | null;
const CATEGORY_ORDER = ["general", "audit", "finance", "research"] as const;

function reasoningLabel(value: "low" | "medium" | "high") {
  if (value === "low") return "Low";
  if (value === "high") return "High";
  return "Medium";
}

function compareCategoryIds(left: string, right: string) {
  const leftIndex = CATEGORY_ORDER.indexOf(left as (typeof CATEGORY_ORDER)[number]);
  const rightIndex = CATEGORY_ORDER.indexOf(right as (typeof CATEGORY_ORDER)[number]);

  if (leftIndex >= 0 && rightIndex >= 0) return leftIndex - rightIndex;
  if (leftIndex >= 0) return -1;
  if (rightIndex >= 0) return 1;
  return 0;
}

function formatSkillCount(count: number) {
  return `${count} ${count === 1 ? "skill" : "skills"}`;
}

export function Composer(props: {
  input: string;
  onInputChange: (value: string) => void;
  onSubmit: (event: FormEvent) => void;
  attachments: Attachment[];
  onAttachFiles: (files: File[]) => void;
  onRemoveAttachment: (id: string) => void;
  models: RichModel[];
  modelKey: string;
  onModelChange: (value: string) => void;
  skills: SkillInfo[];
  skillId: string;
  onSkillChange: (value: string) => void;
  selectedModel?: RichModel;
  temperature: number | null;
  onTemperatureChange: (value: number) => void;
  reasoningEffort: "low" | "medium" | "high" | null;
  onReasoningEffortChange: (value: "low" | "medium" | "high") => void;
  canUseWebTool: boolean;
  enableWebTool: boolean;
  onEnableWebToolChange: (value: boolean) => void;
  loading: boolean;
  conversationId: string;
  onCancelStreaming: () => void;
}) {
  const {
    input,
    onInputChange,
    onSubmit,
    attachments,
    onAttachFiles,
    onRemoveAttachment,
    models,
    modelKey,
    onModelChange,
    skills,
    skillId,
    onSkillChange,
    selectedModel,
    temperature,
    onTemperatureChange,
    reasoningEffort,
    onReasoningEffortChange,
    canUseWebTool,
    enableWebTool,
    onEnableWebToolChange,
    loading,
    conversationId,
    onCancelStreaming
  } = props;

  const [activeMenu, setActiveMenu] = useState<ComposerMenu>(null);
  const [skillCategoryId, setSkillCategoryId] = useState<string | null>(null);

  const rootRef = useRef<HTMLFormElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const selectedSkill = useMemo(() => skills.find((skill) => skill.id === skillId), [skillId, skills]);
  const skillGroups = useMemo(() => {
    const groups = new Map<string, { category: SkillInfo["primary_category"]; skills: SkillInfo[] }>();

    for (const skill of skills) {
      const categoryId = skill.primary_category.id;
      const existing = groups.get(categoryId);
      if (existing) {
        existing.skills.push(skill);
        continue;
      }

      groups.set(categoryId, {
        category: skill.primary_category,
        skills: [skill]
      });
    }

    return Array.from(groups.values())
      .map((group) => ({
        ...group,
        skills: [...group.skills].sort((left, right) => left.name.localeCompare(right.name))
      }))
      .sort((left, right) => {
        const preferredOrder = compareCategoryIds(left.category.id, right.category.id);
        if (preferredOrder !== 0) return preferredOrder;
        return left.category.label.localeCompare(right.category.label);
      });
  }, [skills]);
  const activeSkillGroup = useMemo(
    () => skillGroups.find((group) => group.category.id === skillCategoryId) ?? null,
    [skillCategoryId, skillGroups]
  );
  const modelLabel = selectedModel?.label || "Select model";
  const skillLabel = selectedSkill?.name || "No skill";

  const resizeTextarea = () => {
    if (!textareaRef.current) return;
    textareaRef.current.style.height = "auto";
    textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 180)}px`;
  };

  useEffect(() => {
    resizeTextarea();
  }, [input]);

  useEffect(() => {
    const onPointerDown = (event: MouseEvent) => {
      if (!rootRef.current) return;
      if (rootRef.current.contains(event.target as Node)) return;
      setActiveMenu(null);
    };

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setActiveMenu(null);
    };

    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, []);

  const toggleMenu = (menu: Exclude<ComposerMenu, null>) => {
    if (menu === "skill" && activeMenu !== "skill") setSkillCategoryId(null);
    setActiveMenu((current) => (current === menu ? null : menu));
  };

  const onFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files || []);
    if (files.length > 0) onAttachFiles(files);
    if (event.target) event.target.value = "";
  };

  return (
    <form ref={rootRef} className="composer" onSubmit={onSubmit}>
      {attachments.length > 0 && (
        <div className="attachment-row">
          {attachments.map((file) => (
            <span className="attachment-chip" key={file.id}>
              {file.name}
              <button type="button" aria-label={`Remove ${file.name}`} onClick={() => onRemoveAttachment(file.id)}>
                ×
              </button>
            </span>
          ))}
        </div>
      )}

      <div className="composer-input-row">
        <button
          className="composer-attach-btn"
          type="button"
          title="Attach files"
          aria-label="Attach files"
          onClick={() => fileInputRef.current?.click()}
        >
          <AttachmentIcon />
        </button>
        <input ref={fileInputRef} type="file" multiple className="hidden-file" onChange={onFileChange} />

        <textarea
          ref={textareaRef}
          value={input}
          onChange={(event) => {
            onInputChange(event.target.value);
            resizeTextarea();
          }}
          onKeyDown={(event) => {
            if (event.metaKey && event.key === "Enter") {
              event.preventDefault();
              event.currentTarget.form?.requestSubmit();
            }
          }}
          rows={1}
          placeholder="Ask anything"
          aria-label="Message input"
        />

        {loading ? (
          <button
            className="send-btn stop-btn"
            type="button"
            onClick={onCancelStreaming}
            title="Cancel generation"
            aria-label="Cancel generation"
          >
            <StopIcon />
          </button>
        ) : (
          <button
            className="send-btn"
            type="submit"
            disabled={!conversationId || !selectedModel}
            aria-label="Send message"
          >
            <SendIcon />
          </button>
        )}
      </div>

      <div className="composer-footer">
        <div className="composer-control">
          <button
            className={`composer-trigger ${activeMenu === "model" ? "active" : ""}`}
            type="button"
            aria-label="Select model"
            aria-expanded={activeMenu === "model"}
            onClick={() => toggleMenu("model")}
          >
            <span className="composer-trigger-text">{modelLabel}</span>
            <ChevronDownIcon />
          </button>
          {activeMenu === "model" && (
            <div className="composer-menu" role="dialog" aria-label="Select model">
              <div className="composer-menu-header">
                <h3>Select model</h3>
              </div>
              <div className="composer-menu-list">
                {models.map((item) => {
                  const isSelected = `${item.providerId}::${item.id}` === modelKey;
                  return (
                    <button
                      className={`composer-menu-item ${isSelected ? "active" : ""}`}
                      key={`${item.providerId}:${item.id}`}
                      type="button"
                      onClick={() => {
                        onModelChange(`${item.providerId}::${item.id}`);
                        setActiveMenu(null);
                      }}
                    >
                      <span className="composer-menu-item-copy">
                        <strong>{item.label}</strong>
                        <span>{item.providerLabel}</span>
                      </span>
                      {isSelected && <CheckIcon />}
                    </button>
                  );
                })}
              </div>
            </div>
          )}
        </div>

        <div className="composer-control">
          <button
            className={`composer-trigger ${activeMenu === "skill" ? "active" : ""}`}
            type="button"
            aria-label="Select skill"
            aria-expanded={activeMenu === "skill"}
            onClick={() => toggleMenu("skill")}
          >
            <span className="composer-trigger-text">{skillLabel}</span>
            <ChevronDownIcon />
          </button>
          {activeMenu === "skill" && (
            <div className="composer-menu" role="dialog" aria-label="Select skill">
              <div className="composer-menu-header">
                {activeSkillGroup ? (
                  <>
                    <button
                      className="composer-menu-back"
                      type="button"
                      aria-label="Back to skill categories"
                      onClick={() => setSkillCategoryId(null)}
                    >
                      <ChevronLeftIcon />
                      <span>Back</span>
                    </button>
                    <p className="composer-menu-title">{activeSkillGroup.category.label}</p>
                  </>
                ) : (
                  <h3>Select skill</h3>
                )}
              </div>
              <div className="composer-menu-list">
                {activeSkillGroup ? (
                  activeSkillGroup.skills.map((skill) => {
                    const isSelected = skill.id === skillId;
                    return (
                      <button
                        className={`composer-menu-item ${isSelected ? "active" : ""}`}
                        key={skill.id}
                        type="button"
                        onClick={() => {
                          onSkillChange(skill.id);
                          setActiveMenu(null);
                        }}
                      >
                        <span className="composer-menu-item-copy">
                          <strong>{skill.name}</strong>
                          <span>{skill.description}</span>
                          <span className="composer-skill-tags">
                            {skill.tags.map((tag) => (
                              <span className="composer-skill-tag" key={tag}>
                                {tag}
                              </span>
                            ))}
                          </span>
                        </span>
                        {isSelected && <CheckIcon />}
                      </button>
                    );
                  })
                ) : (
                  <>
                    <button
                      className={`composer-menu-item ${skillId ? "" : "active"}`}
                      type="button"
                      onClick={() => {
                        onSkillChange("");
                        setActiveMenu(null);
                      }}
                    >
                      <span className="composer-menu-item-copy">
                        <strong>No skill</strong>
                        <span>Use the selected model directly</span>
                      </span>
                      {!skillId && <CheckIcon />}
                    </button>
                    {skillGroups.map((group) => (
                      <button
                        className="composer-menu-item composer-menu-item-branch"
                        key={group.category.id}
                        type="button"
                        onClick={() => setSkillCategoryId(group.category.id)}
                      >
                        <span className="composer-menu-item-copy">
                          <strong>{group.category.label}</strong>
                          <span>{formatSkillCount(group.skills.length)}</span>
                        </span>
                        <ChevronRightIcon />
                      </button>
                    ))}
                  </>
                )}
              </div>
            </div>
          )}
        </div>

        <div className="composer-control composer-control-right">
          <button
            className={`composer-trigger composer-trigger-icon ${activeMenu === "settings" ? "active" : ""}`}
            type="button"
            aria-label="Open chat settings"
            aria-expanded={activeMenu === "settings"}
            onClick={() => toggleMenu("settings")}
          >
            <SettingsIcon />
            <span className="composer-trigger-text">Settings</span>
          </button>
          {activeMenu === "settings" && (
            <div className="composer-menu composer-menu-right" role="dialog" aria-label="Chat settings">
              <div className="composer-menu-header">
                <h3>Chat settings</h3>
              </div>

              <div className="composer-settings-stack">
                {selectedModel?.supports_temperature && (
                  <section className="composer-settings-section">
                    <p>Temperature</p>
                    <label className="composer-number-row">
                      <span>Creativity</span>
                      <input
                        className="composer-number-input"
                        type="number"
                        value={temperature ?? 0.3}
                        step={0.1}
                        min={0}
                        max={2}
                        onChange={(event) => onTemperatureChange(Number(event.target.value))}
                        aria-label="Temperature"
                      />
                    </label>
                  </section>
                )}

                {selectedModel?.supports_reasoning_effort && (
                  <section className="composer-settings-section">
                    <p>Reasoning</p>
                    <div className="composer-choice-group">
                      {(["low", "medium", "high"] as const).map((value) => (
                        <button
                          className={`composer-choice ${value === (reasoningEffort ?? "medium") ? "active" : ""}`}
                          key={value}
                          type="button"
                          onClick={() => onReasoningEffortChange(value)}
                        >
                          {reasoningLabel(value)}
                        </button>
                      ))}
                    </div>
                  </section>
                )}

                {canUseWebTool && (
                  <section className="composer-settings-section">
                    <p>Tools</p>
                    <button
                      className={`composer-toggle-row ${enableWebTool ? "enabled" : ""}`}
                      type="button"
                      aria-pressed={enableWebTool}
                      onClick={() => onEnableWebToolChange(!enableWebTool)}
                    >
                      <span className="composer-toggle-copy">
                        <strong>Web search</strong>
                        <span>Enable the built-in web tool for this chat</span>
                      </span>
                      <span className="composer-switch" aria-hidden="true" />
                    </button>
                  </section>
                )}

                {!selectedModel?.supports_temperature &&
                  !selectedModel?.supports_reasoning_effort &&
                  !canUseWebTool && <p className="composer-settings-empty">No additional settings available.</p>}
              </div>
            </div>
          )}
        </div>

        <p className="composer-hint">Cmd + Enter to send</p>
      </div>
    </form>
  );
}
