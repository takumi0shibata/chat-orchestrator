import { ChangeEvent, FormEvent, useRef } from "react";

import type { ModelInfo, SkillInfo } from "../types";
import { ChevronDownIcon, PlusIcon, SendIcon, StopIcon } from "./Icons";

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

  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const resizeTextarea = () => {
    if (!textareaRef.current) return;
    textareaRef.current.style.height = "auto";
    textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 180)}px`;
  };

  const onFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files || []);
    if (files.length > 0) onAttachFiles(files);
    if (event.target) event.target.value = "";
  };

  return (
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
        rows={2}
        placeholder="Message Orchestrator..."
      />

      <div className="composer-tools">
        <button className="icon-btn" type="button" title="Attach files" onClick={() => fileInputRef.current?.click()}>
          <PlusIcon />
        </button>
        <input ref={fileInputRef} type="file" multiple className="hidden-file" onChange={onFileChange} />

        <div className="select-wrap">
          <select value={modelKey} onChange={(event) => onModelChange(event.target.value)} title="Model">
            {models.map((item) => (
              <option value={`${item.providerId}::${item.id}`} key={`${item.providerId}:${item.id}`}>
                {item.label} ({item.providerLabel})
              </option>
            ))}
          </select>
          <ChevronDownIcon />
        </div>

        <div className="select-wrap">
          <select value={skillId} onChange={(event) => onSkillChange(event.target.value)} title="Skill">
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
            onChange={(event) => onTemperatureChange(Number(event.target.value))}
            title="Temperature"
          />
        )}

        {selectedModel?.supports_reasoning_effort && (
          <div className="select-wrap">
            <select
              value={reasoningEffort ?? "medium"}
              onChange={(event) => onReasoningEffortChange(event.target.value as "low" | "medium" | "high")}
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
            <input type="checkbox" checked={enableWebTool} onChange={(event) => onEnableWebToolChange(event.target.checked)} />
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
  );
}
