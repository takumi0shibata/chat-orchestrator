import { useEffect, useMemo, useRef } from "react";

import { Composer } from "./components/Composer";
import { ConversationSidebar } from "./components/ConversationSidebar";
import { MessageList } from "./components/MessageList";
import { useChatController } from "./hooks/useChatController";

export function App() {
  const controller = useChatController();
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const activeConversation = useMemo(
    () => controller.conversations.find((item) => item.id === controller.conversationId),
    [controller.conversations, controller.conversationId]
  );

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [controller.messages, controller.loading]);

  const conversationLabel = activeConversation?.title || "New chat";
  const conversationMeta = activeConversation
    ? `${activeConversation.message_count} messages`
    : "Ready for a new conversation";

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
            <p>{conversationMeta}</p>
          </div>
        </header>

        <div className="chat-stage">
          <div className="chat-column">
            <MessageList
              messages={controller.messages}
              loading={controller.loading}
              showThinking={controller.showThinking}
              showSkillRunning={controller.showSkillRunning}
              selectedSkillName={controller.selectedSkill?.name}
              endRef={messagesEndRef}
              onFeedback={(action, choice) => void controller.onSubmitFeedback(action, choice)}
            />

            <div className="chat-composer-slot">
              <Composer
                input={controller.input}
                onInputChange={controller.setInput}
                onSubmit={(event) => void controller.onSubmit(event)}
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
