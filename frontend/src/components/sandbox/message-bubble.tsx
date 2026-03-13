import { Code2, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useSandboxStore } from "@/stores/sandbox-store";
import { useDeleteMessage } from "@/hooks/use-sandbox";
import type { SandboxMessage } from "@/types/sandbox";

interface MessageBubbleProps {
  message: SandboxMessage;
}

function formatTime(dateString: string): string {
  const date = new Date(dateString);
  return date.toLocaleTimeString("en-US", {
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  });
}

function MessageBubble({ message }: MessageBubbleProps) {
  const isInbound = message.direction === "inbound";
  const { inspectedMessageId, setInspectedMessageId } = useSandboxStore();
  const isInspected = inspectedMessageId === message.id;
  const deleteMessage = useDeleteMessage();

  const handleInspect = () => {
    setInspectedMessageId(isInspected ? null : message.id);
  };

  const handleDelete = (e: React.MouseEvent) => {
    e.stopPropagation();
    deleteMessage.mutate(message.id, {
      onSuccess: () => {
        toast.success("Message deleted");
        if (isInspected) setInspectedMessageId(null);
      },
      onError: (error) => {
        toast.error("Failed to delete message", { description: error.message });
      },
    });
  };

  return (
    <div
      className={cn(
        "flex w-full group",
        isInbound ? "justify-start" : "justify-end"
      )}
    >
      <div className="relative max-w-[75%]">
        <button
          type="button"
          onClick={handleInspect}
          className={cn(
            "w-full text-left rounded-lg px-3 py-2 text-sm transition-shadow cursor-pointer",
            isInbound
              ? "bg-muted text-foreground rounded-bl-none"
              : "bg-primary text-primary-foreground rounded-br-none",
            message.is_deleted && "opacity-50",
            isInspected && "ring-2 ring-blue-500 dark:ring-blue-400 ring-offset-1 ring-offset-background"
          )}
        >
          <div
            className={cn(
              "text-xs font-medium mb-1",
              isInbound ? "text-muted-foreground" : "text-primary-foreground/80"
            )}
          >
            {message.sender}
          </div>
          <p className={cn(message.is_deleted && "line-through")}>
            {message.content}
          </p>
          <div
            className={cn(
              "flex items-center gap-1.5 mt-1",
              isInbound ? "text-muted-foreground" : "text-primary-foreground/70"
            )}
          >
            {message.content_type !== "text" && (
              <Badge
                variant={isInbound ? "secondary" : "outline"}
                className="text-[10px] px-1 py-0"
              >
                {message.content_type}
              </Badge>
            )}
            <span className="text-[10px] ml-auto">{formatTime(message.created_at)}</span>
          </div>
        </button>

        {/* Action icons - visible on hover */}
        <div
          className={cn(
            "absolute -top-2 flex gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity",
            isInbound ? "-right-2" : "-left-2"
          )}
        >
          <Button
            variant="secondary"
            size="icon"
            className="h-6 w-6 rounded-full shadow-sm"
            onClick={(e) => {
              e.stopPropagation();
              handleInspect();
            }}
          >
            <Code2 className="h-3 w-3" />
          </Button>
          <Button
            variant="secondary"
            size="icon"
            className="h-6 w-6 rounded-full shadow-sm hover:bg-destructive hover:text-destructive-foreground"
            onClick={handleDelete}
          >
            <Trash2 className="h-3 w-3" />
          </Button>
        </div>
      </div>
    </div>
  );
}

export { MessageBubble };
