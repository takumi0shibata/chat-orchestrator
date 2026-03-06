import { useEffect, useRef } from "react";

import { Composer } from "./components/Composer";
import { ConversationSidebar } from "./components/ConversationSidebar";
import { MessageList } from "./components/MessageList";
import { useChatController } from "./hooks/useChatController";

export function App() {
  const controller = useChatController();
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [controller.messages, controller.loading]);

  return (
    <div className={`app-shell ${controller.sidebarOpen ? "" : "sidebar-collapsed"}`}>
      <ConversationSidebar
        sidebarOpen={controller.sidebarOpen}
        conversations={controller.conversations}
        conversationId={controller.conversationId}
        onNewChat={controller.onNewChat}
        onDeleteAll={controller.onDeleteAllConversations}
        onSelectConversation={(id) => void controller.onSelectConversation(id)}
        onDeleteConversation={(id) => void controller.onDeleteConversation(id)}
      />

      <main className="chat-main">
        <button
          className="sidebar-toggle"
          type="button"
          onClick={() => controller.setSidebarOpen((prev) => !prev)}
          title={controller.sidebarOpen ? "Hide history" : "Show history"}
        >
          {controller.sidebarOpen ? "<" : ">"}
        </button>

        <MessageList
          messages={controller.messages}
          loading={controller.loading}
          showThinking={controller.showThinking}
          showSkillRunning={controller.showSkillRunning}
          selectedSkillName={controller.selectedSkill?.name}
          endRef={messagesEndRef}
          onFeedback={(action, choice) => void controller.onSubmitFeedback(action, choice)}
        />

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
      </main>
    </div>
  );
}
