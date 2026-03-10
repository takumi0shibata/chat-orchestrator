import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties, UIEvent } from "react";

import { Composer } from "./components/Composer";
import { ConversationSidebar } from "./components/ConversationSidebar";
import { MessageList } from "./components/MessageList";
import { useChatController } from "./hooks/useChatController";

const AUTO_SCROLL_THRESHOLD_PX = 96;
const COMPOSER_RESERVE_FALLBACK_PX = 220;
const COMPOSER_RESERVE_OFFSET_PX = 24;

function getDistanceFromBottom(node: HTMLElement) {
  return node.scrollHeight - node.scrollTop - node.clientHeight;
}

export function App() {
  const controller = useChatController();
  const chatStageRef = useRef<HTMLDivElement>(null);
  const composerSlotRef = useRef<HTMLDivElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const autoScrollEnabledRef = useRef(true);
  const [composerReserve, setComposerReserve] = useState(COMPOSER_RESERVE_FALLBACK_PX);

  const activeConversation = useMemo(
    () => controller.conversations.find((item) => item.id === controller.conversationId),
    [controller.conversations, controller.conversationId]
  );
  const activeSkillName = useMemo(
    () => controller.skills.find((item) => item.id === controller.skillStatus?.skill_id)?.name,
    [controller.skills, controller.skillStatus]
  );

  const scrollMessagesToBottom = useCallback(() => {
    if (!autoScrollEnabledRef.current) return;
    messagesEndRef.current?.scrollIntoView({ block: "end" });
  }, []);

  useEffect(() => {
    const node = composerSlotRef.current;
    if (!node) return;

    const updateReserve = () => {
      const nextReserve = Math.max(
        COMPOSER_RESERVE_FALLBACK_PX,
        Math.ceil(node.getBoundingClientRect().height) + COMPOSER_RESERVE_OFFSET_PX
      );
      setComposerReserve((current) => (current === nextReserve ? current : nextReserve));
    };

    updateReserve();

    if (typeof ResizeObserver === "undefined") return;

    const observer = new ResizeObserver(() => {
      updateReserve();
    });

    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    autoScrollEnabledRef.current = true;
  }, [controller.conversationId]);

  useEffect(() => {
    if (!controller.loading) return;
    autoScrollEnabledRef.current = true;
  }, [controller.loading]);

  useEffect(() => {
    scrollMessagesToBottom();
  }, [controller.messages, controller.loading, scrollMessagesToBottom]);

  const conversationLabel = activeConversation?.title || "New chat";

  const onChatStageScroll = useCallback((event: UIEvent<HTMLDivElement>) => {
    const isNearBottom = getDistanceFromBottom(event.currentTarget) <= AUTO_SCROLL_THRESHOLD_PX;
    autoScrollEnabledRef.current = isNearBottom;
  }, []);

  const onSelectConversation = (id: string) => {
    void controller.onSelectConversation(id);
    if (window.matchMedia("(max-width: 960px)").matches) {
      controller.setSidebarOpen(false);
    }
  };

  return (
    <div className="app-shell">
      <ConversationSidebar
        sidebarOpen={controller.sidebarOpen}
        conversations={controller.conversations}
        conversationId={controller.conversationId}
        onToggleSidebar={() => controller.setSidebarOpen((prev) => !prev)}
        onNewChat={controller.onNewChat}
        onDeleteAll={controller.onDeleteAllConversations}
        onSelectConversation={onSelectConversation}
        onDeleteConversation={(id) => void controller.onDeleteConversation(id)}
      />

      <main className="chat-main">
        <header className="chat-topbar">
          <div className="topbar-copy">
            <span className="topbar-eyebrow">Conversation</span>
            <h1>{conversationLabel}</h1>
          </div>
        </header>

        <div
          ref={chatStageRef}
          className="chat-stage"
          onScroll={onChatStageScroll}
          style={{ "--composer-reserve": `${composerReserve}px` } as CSSProperties}
        >
          <div className="chat-column">
            <MessageList
              messages={controller.messages}
              loading={controller.loading}
              showThinking={controller.showThinking}
              skillStatus={controller.skillStatus}
              activeSkillName={activeSkillName}
              endRef={messagesEndRef}
              onFeedback={(action, choice) => void controller.onSubmitFeedback(action, choice)}
            />

            <div ref={composerSlotRef} className="chat-composer-slot">
              <Composer
                input={controller.input}
                onInputChange={controller.setInput}
                onSubmit={(event) => void controller.onSubmit(event)}
                isParsingAttachments={controller.isParsingAttachments}
                parsingAttachmentLabel={controller.parsingAttachmentLabel}
                attachments={controller.attachments}
                onAttachFiles={(files) => void controller.onAttachFiles(files)}
                onRemoveAttachment={controller.onRemoveAttachment}
                models={controller.models}
                modelKey={controller.modelKey}
                onModelChange={controller.onModelChange}
                skills={controller.skills}
                skillId={controller.skillId}
                onSkillChange={controller.setSkillId}
                selectedModel={controller.selectedModel}
                temperature={controller.temperature}
                onTemperatureChange={controller.setTemperature}
                reasoningEffort={controller.reasoningEffort}
                onReasoningEffortChange={controller.setReasoningEffort}
                canUseWebTool={controller.canUseWebTool}
                enableWebTool={controller.enableWebTool}
                onEnableWebToolChange={controller.setEnableWebTool}
                loading={controller.loading}
                conversationId={controller.conversationId}
                onCancelStreaming={controller.onCancelStreaming}
              />

              {controller.error && <p className="error">{controller.error}</p>}
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
