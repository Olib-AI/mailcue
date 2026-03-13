import { useState } from "react";
import { MessageSquare, MessagesSquare, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useConversations, useDeleteConversation } from "@/hooks/use-sandbox";
import { useSandboxStore } from "@/stores/sandbox-store";

function ConversationList() {
  const { selectedProviderId, selectedConversationId, setSelectedConversationId } =
    useSandboxStore();
  const { data: conversations, isLoading } = useConversations(selectedProviderId);
  const deleteConversation = useDeleteConversation();
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  const handleDelete = (e: React.MouseEvent, conversationId: string) => {
    e.stopPropagation();
    if (!selectedProviderId) return;

    if (confirmDeleteId === conversationId) {
      deleteConversation.mutate(
        { providerId: selectedProviderId, conversationId },
        {
          onSuccess: () => {
            toast.success("Conversation deleted");
            if (selectedConversationId === conversationId) {
              setSelectedConversationId(null);
            }
            setConfirmDeleteId(null);
          },
          onError: (error) => {
            toast.error("Failed to delete conversation", { description: error.message });
            setConfirmDeleteId(null);
          },
        }
      );
    } else {
      setConfirmDeleteId(conversationId);
    }
  };

  if (!selectedProviderId) {
    return (
      <>
        <div className="flex items-center border-b px-3 h-12 shrink-0">
          <h2 className="text-sm font-semibold">Conversations</h2>
        </div>
        <div className="flex-1 flex items-center justify-center p-4">
          <p className="text-sm text-muted-foreground text-center">
            Select a provider to view conversations
          </p>
        </div>
      </>
    );
  }

  return (
    <>
      <div className="flex items-center border-b px-3 h-12 shrink-0">
        <h2 className="text-sm font-semibold">Conversations</h2>
      </div>

      <ScrollArea className="flex-1">
        <div className="p-2 space-y-0.5">
          {/* All Messages option */}
          <button
            type="button"
            onClick={() => setSelectedConversationId(null)}
            className={cn(
              "flex w-full items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium transition-colors",
              selectedConversationId === null
                ? "bg-accent text-accent-foreground"
                : "text-muted-foreground hover:bg-muted/50 hover:text-foreground"
            )}
          >
            <MessagesSquare className="h-4 w-4 shrink-0" />
            All Messages
          </button>

          {isLoading ? (
            <>
              <Skeleton className="h-10 w-full rounded-md" />
              <Skeleton className="h-10 w-full rounded-md" />
            </>
          ) : !conversations || conversations.length === 0 ? (
            <div className="px-3 py-6 text-center text-sm text-muted-foreground">
              No conversations yet. Simulate a message to create one.
            </div>
          ) : (
            conversations.map((conversation) => (
              <div
                key={conversation.id}
                className={cn(
                  "group relative flex w-full items-start gap-2.5 rounded-md px-3 py-2 text-sm transition-colors text-left cursor-pointer",
                  selectedConversationId === conversation.id
                    ? "bg-accent text-accent-foreground"
                    : "hover:bg-muted/50"
                )}
                onClick={() => setSelectedConversationId(conversation.id)}
                onMouseLeave={() => {
                  if (confirmDeleteId === conversation.id) setConfirmDeleteId(null);
                }}
              >
                <MessageSquare className="h-4 w-4 shrink-0 mt-0.5" />
                <div className="flex-1 min-w-0">
                  <span className="font-medium truncate block">
                    {conversation.name ?? conversation.external_id}
                  </span>
                  <Badge
                    variant="outline"
                    className="text-[10px] px-1.5 py-0 mt-1"
                  >
                    {conversation.conversation_type}
                  </Badge>
                </div>

                {/* Delete button - visible on hover */}
                <Button
                  variant={confirmDeleteId === conversation.id ? "destructive" : "ghost"}
                  size="icon"
                  className="absolute top-1.5 right-1.5 h-6 w-6 opacity-0 group-hover:opacity-100 transition-opacity"
                  onClick={(e) => handleDelete(e, conversation.id)}
                >
                  <Trash2 className="h-3 w-3" />
                </Button>
              </div>
            ))
          )}
        </div>
      </ScrollArea>
    </>
  );
}

export { ConversationList };
