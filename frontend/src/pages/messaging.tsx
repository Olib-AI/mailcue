import { ProviderList } from "@/components/sandbox/provider-list";
import { ConversationList } from "@/components/sandbox/conversation-list";
import { MessageThread } from "@/components/sandbox/message-thread";

function MessagingPage() {
  return (
    <div className="flex h-full">
      {/* Provider list */}
      <div className="w-64 min-w-[220px] border-r flex flex-col overflow-hidden">
        <ProviderList />
      </div>

      {/* Conversation list */}
      <div className="w-64 min-w-[220px] border-r flex flex-col overflow-hidden">
        <ConversationList />
      </div>

      {/* Message thread */}
      <div className="flex-1 flex flex-col overflow-hidden">
        <MessageThread />
      </div>
    </div>
  );
}

export { MessagingPage };
