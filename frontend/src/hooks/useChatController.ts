import { FormEvent, useEffect, useMemo, useRef, useState } from "react";

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
  streamChat,
  submitSkillFeedback
} from "../api";
import type {
  AttachmentSummary,
  ChatMessage,
  FeedbackAction,
  FeedbackChoice,
  ModelInfo,
  ProviderInfo,
  ReasoningEffort,
  SkillInfo
} from "../types";

const ACTIVE_CONVERSATION_KEY = "chat_orchestrator_active_conversation_id";

export type Attachment = {
  id: AttachmentSummary["id"];
  name: AttachmentSummary["name"];
  content_type: AttachmentSummary["content_type"];
  size_bytes: AttachmentSummary["size_bytes"];
};

export type RichModel = ModelInfo & {
  providerId: string;
  providerLabel: string;
  providerEnabled: boolean;
};

function normalizeMessage(message: ChatMessage): ChatMessage {
  return {
    ...message,
    artifacts: message.artifacts || [],
    skill_id: message.skill_id ?? null,
    attachments: message.attachments || []
  };
}

function resolveReasoningEffort(model: ModelInfo, current: ReasoningEffort | null): ReasoningEffort | null {
  if (!model.supports_reasoning_effort) return null;
  if (current && model.reasoning_effort_options.includes(current)) return current;
  return model.default_reasoning_effort ?? model.reasoning_effort_options[0] ?? null;
}

function applyFeedbackSelection(
  messages: ChatMessage[],
  runId: string,
  itemId: string,
  decision: string
): ChatMessage[] {
  return messages.map((message) => {
    if (message.role !== "assistant" || message.artifacts.length === 0) return message;
    return {
      ...message,
      artifacts: message.artifacts.map((artifact) => {
        if (artifact.type !== "card_list") return artifact;
        return {
          ...artifact,
          sections: artifact.sections.map((section) => ({
            ...section,
            items: section.items.map((item) => ({
              ...item,
              actions: item.actions.map((action) => {
                if (action.type !== "feedback") return action;
                if (action.run_id !== runId || action.item_id !== itemId) return action;
                return { ...action, selected: decision };
              })
            }))
          }))
        };
      })
    };
  });
}

export function useChatController() {
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [conversations, setConversations] = useState<{ id: string; title: string; updated_at: string; message_count: number }[]>([]);
  const [models, setModels] = useState<RichModel[]>([]);

  const [modelKey, setModelKey] = useState<string>("");
  const [skillId, setSkillId] = useState<string>("");
  const [temperature, setTemperature] = useState<number | null>(0.3);
  const [reasoningEffort, setReasoningEffort] = useState<ReasoningEffort | null>(null);
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

  const selectConversation = async (id: string, persist = true) => {
    const history = await fetchConversationMessages(id);
    setConversationId(id);
    setMessages(history.map(normalizeMessage));
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
      setReasoningEffort(resolveReasoningEffort(initial, null));
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

  useEffect(() => {
    if (!canUseWebTool && enableWebTool) setEnableWebTool(false);
  }, [canUseWebTool, enableWebTool]);

  const onModelChange = (value: string) => {
    setModelKey(value);
    const item = models.find((entry) => `${entry.providerId}::${entry.id}` === value);
    if (!item) return;

    if (!item.supports_temperature) setTemperature(null);
    else if (temperature === null) setTemperature(item.default_temperature ?? 0.3);

    setReasoningEffort(resolveReasoningEffort(item, reasoningEffort));

    if (!(item.api_mode === "responses" && (item.providerId === "openai" || item.providerId === "azure_openai"))) {
      setEnableWebTool(false);
    }
  };

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

  const onAttachFiles = async (files: File[]) => {
    try {
      if (!conversationId) return;
      const extracted = await extractAttachments({ conversationId, files });
      const next = extracted.map((file) => ({
        id: file.id,
        name: file.name,
        content_type: file.content_type,
        size_bytes: file.size_bytes
      }));
      setAttachments((prev) => [...prev, ...next]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "ファイルの読み込みに失敗しました");
    }
  };

  const onRemoveAttachment = (id: string) => {
    setAttachments((prev) => prev.filter((item) => item.id !== id));
  };

  const onCancelStreaming = () => {
    abortControllerRef.current?.abort();
  };

  const onSubmitFeedback = async (action: FeedbackAction, choice: FeedbackChoice) => {
    if (!conversationId || action.selected) return;

    try {
      await submitSkillFeedback({
        conversationId,
        runId: action.run_id,
        itemId: action.item_id,
        decision: choice.value
      });
      setMessages((prev) => applyFeedbackSelection(prev, action.run_id, action.item_id, choice.value));
    } catch (e) {
      setError(e instanceof Error ? e.message : "フィードバック送信に失敗しました");
    }
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

    const userRaw = trimmed;
    const queuedAttachments = attachments;

    setInput("");
    setAttachments([]);

    const userMessage: ChatMessage = {
      role: "user",
      content: userRaw,
      artifacts: [],
      skill_id: null,
      attachments: queuedAttachments
    };
    const assistantPlaceholder: ChatMessage = {
      role: "assistant",
      content: "",
      artifacts: [],
      skill_id: skillId || null,
      attachments: []
    };
    setMessages((prev) => [...prev, userMessage, assistantPlaceholder]);
    const abortController = new AbortController();
    abortControllerRef.current = abortController;

    try {
      const done = await streamChat({
        providerId: selectedModel.providerId,
        model: selectedModel.id,
        userInput: userRaw,
        attachmentIds: queuedAttachments.map((attachment) => attachment.id),
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

      setMessages((prev) => {
        const next = [...prev];
        const lastIndex = next.length - 1;
        if (lastIndex >= 0 && next[lastIndex].role === "assistant") {
          next[lastIndex] = normalizeMessage(done.message);
        }
        return next;
      });

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
        setAttachments(queuedAttachments);
        setMessages((prev) => prev.slice(0, -2));
      }
    } finally {
      abortControllerRef.current = null;
      setLoading(false);
      setShowThinking(false);
      setShowSkillRunning(false);
    }
  };

  return {
    skills,
    conversations,
    models,
    modelKey,
    skillId,
    temperature,
    reasoningEffort,
    enableWebTool,
    conversationId,
    messages,
    input,
    attachments,
    error,
    loading,
    showThinking,
    showSkillRunning,
    sidebarOpen,
    selectedModel,
    selectedSkill,
    canUseWebTool,
    setInput,
    setSkillId,
    setTemperature,
    setReasoningEffort,
    setEnableWebTool,
    setSidebarOpen,
    onModelChange,
    onNewChat,
    onDeleteConversation,
    onDeleteAllConversations,
    onSelectConversation: selectConversation,
    onAttachFiles,
    onRemoveAttachment,
    onCancelStreaming,
    onSubmitFeedback,
    onSubmit
  };
}
