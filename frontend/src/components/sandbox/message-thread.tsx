import { useEffect, useRef, useState } from "react";
import { Copy, Check, Plus, Send, ExternalLink, Inbox, ChevronDown, ChevronRight } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Input } from "@/components/ui/input";
import { useMessages, useProvider, useWebhookDeliveries, useSendMessage } from "@/hooks/use-sandbox";
import { useSandboxStore } from "@/stores/sandbox-store";
import { MessageBubble } from "./message-bubble";
import { SimulateDialog } from "./simulate-dialog";
import { WebhookConfig } from "./webhook-config";
import { RequestInspector, JsonBlock } from "./request-inspector";
import type { WebhookDelivery } from "@/types/sandbox";

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    void navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  return (
    <Button variant="ghost" size="icon" className="h-7 w-7" onClick={handleCopy}>
      {copied ? (
        <Check className="h-3.5 w-3.5 text-green-500" />
      ) : (
        <Copy className="h-3.5 w-3.5" />
      )}
    </Button>
  );
}

// ---------------------------------------------------------------------------
// DeliveriesPanel - expandable delivery rows with payload/response JSON
// ---------------------------------------------------------------------------

interface DeliveriesPanelProps {
  deliveries: WebhookDelivery[] | undefined;
}

function DeliveryRow({ delivery }: { delivery: WebhookDelivery }) {
  const [expanded, setExpanded] = useState(false);

  const isSuccess =
    delivery.status_code !== null &&
    delivery.status_code >= 200 &&
    delivery.status_code < 300;

  let parsedResponseBody: unknown = null;
  if (delivery.response_body) {
    try {
      parsedResponseBody = JSON.parse(delivery.response_body) as unknown;
    } catch {
      parsedResponseBody = delivery.response_body;
    }
  }

  return (
    <div className="rounded border text-xs">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center gap-2 px-2.5 py-1.5 hover:bg-muted/50 transition-colors cursor-pointer"
      >
        {expanded ? (
          <ChevronDown className="h-3 w-3 shrink-0 text-muted-foreground" />
        ) : (
          <ChevronRight className="h-3 w-3 shrink-0 text-muted-foreground" />
        )}
        <Badge
          variant={isSuccess ? "default" : "destructive"}
          className="text-[10px] px-1.5 py-0 shrink-0"
        >
          {delivery.status_code ?? "pending"}
        </Badge>
        <span className="font-mono truncate">{delivery.event_type}</span>
        <span className="text-muted-foreground ml-auto shrink-0">
          #{delivery.attempt}
        </span>
        <span className="text-muted-foreground shrink-0">
          {delivery.delivered_at
            ? new Date(delivery.delivered_at).toLocaleTimeString()
            : "pending"}
        </span>
      </button>
      {expanded && (
        <div className="border-t px-2.5 py-2 space-y-2">
          <JsonBlock data={delivery.payload} label="Webhook Payload" />
          <JsonBlock data={parsedResponseBody} label="Response Body" />
        </div>
      )}
    </div>
  );
}

function DeliveriesPanel({ deliveries }: DeliveriesPanelProps) {
  if (!deliveries || deliveries.length === 0) {
    return (
      <p className="text-xs text-muted-foreground py-3">
        No webhook deliveries yet.
      </p>
    );
  }

  return (
    <div className="space-y-1.5">
      {deliveries.map((delivery) => (
        <DeliveryRow key={delivery.id} delivery={delivery} />
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// ComposeBar – inline message input at the bottom of the thread
// ---------------------------------------------------------------------------

function ComposeBar({ providerId, conversationId }: { providerId: string; conversationId?: string | null }) {
  const [message, setMessage] = useState("");
  const [sender, setSender] = useState("User");
  const sendMessage = useSendMessage();

  const handleSend = () => {
    const text = message.trim();
    if (!text) return;

    sendMessage.mutate(
      {
        providerId,
        data: {
          sender: sender.trim() || "User",
          content: text,
          content_type: "text",
          conversation_id: conversationId ?? undefined,
        },
      },
      {
        onSuccess: () => setMessage(""),
      }
    );
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  if (!conversationId) {
    return (
      <div className="border-t px-4 py-2 shrink-0">
        <p className="text-xs text-muted-foreground text-center py-1">
          Select a conversation to send messages, or use Simulate Inbound to start one.
        </p>
      </div>
    );
  }

  return (
    <div className="border-t px-4 py-2 shrink-0">
      <div className="flex items-center gap-2">
        <Input
          value={sender}
          onChange={(e) => setSender(e.target.value)}
          placeholder="Sender"
          className="w-24 h-8 text-xs shrink-0"
        />
        <Input
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Type a message…"
          className="flex-1 h-8 text-sm"
          disabled={sendMessage.isPending}
        />
        <Button
          variant="default"
          size="icon"
          className="h-8 w-8 shrink-0"
          onClick={handleSend}
          disabled={!message.trim() || sendMessage.isPending}
        >
          <Send className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}

function MessageThread() {
  const { selectedProviderId, selectedConversationId, inspectedMessageId } = useSandboxStore();
  const { data: provider } = useProvider(selectedProviderId);
  const { data: messageData, isLoading } = useMessages(
    selectedProviderId,
    selectedConversationId
  );
  const { data: deliveries } = useWebhookDeliveries(selectedProviderId);
  const [simulateOpen, setSimulateOpen] = useState(false);
  const scrollEndRef = useRef<HTMLDivElement>(null);

  const messages = messageData?.messages ?? [];

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    scrollEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length]);

  if (!selectedProviderId) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-3 text-muted-foreground">
        <Inbox className="h-12 w-12 opacity-40" />
        <p className="text-sm">Select a provider to view messages</p>
      </div>
    );
  }

  return (
    <>
      {/* Top bar with sandbox URL */}
      <div className="flex items-center justify-between border-b px-4 h-12 shrink-0 gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-sm font-semibold truncate">
            {provider?.name ?? "Messages"}
          </span>
        </div>
        {provider?.sandbox_url && (
          <div className="flex items-center gap-1 shrink-0">
            <Badge variant="outline" className="text-xs font-mono max-w-[280px] truncate">
              {provider.sandbox_url}
            </Badge>
            <CopyButton text={provider.sandbox_url} />
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              onClick={() => window.open(provider.sandbox_url, "_blank")}
            >
              <ExternalLink className="h-3.5 w-3.5" />
            </Button>
          </div>
        )}
      </div>

      {/* Messages area */}
      <div className="flex-1 overflow-hidden flex flex-col">
        <ScrollArea className="flex-1 px-4">
          <div className="py-4 space-y-3">
            {isLoading ? (
              <>
                <div className="flex justify-start">
                  <Skeleton className="h-16 w-48 rounded-lg" />
                </div>
                <div className="flex justify-end">
                  <Skeleton className="h-16 w-48 rounded-lg" />
                </div>
                <div className="flex justify-start">
                  <Skeleton className="h-16 w-56 rounded-lg" />
                </div>
              </>
            ) : messages.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-12 text-muted-foreground gap-2">
                <Inbox className="h-8 w-8 opacity-40" />
                <p className="text-sm">No messages yet</p>
                <p className="text-xs">
                  Type a message below to get started
                </p>
              </div>
            ) : (
              messages.map((message) => (
                <MessageBubble key={message.id} message={message} />
              ))
            )}
            <div ref={scrollEndRef} />
          </div>
        </ScrollArea>
      </div>

      {/* Compose bar */}
      <ComposeBar providerId={selectedProviderId} conversationId={selectedConversationId} />

      {/* Bottom panel: Inspector (when message selected) or Tabs (default) */}
      {inspectedMessageId ? (
        <RequestInspector messages={messages} />
      ) : (
        <div className="border-t shrink-0">
          <Tabs defaultValue="webhooks" className="w-full">
            <div className="flex items-center justify-between px-4 pt-2">
              <TabsList>
                <TabsTrigger value="webhooks">Webhooks</TabsTrigger>
                <TabsTrigger value="deliveries">Deliveries</TabsTrigger>
              </TabsList>
              <Button
                variant="default"
                size="sm"
                className="gap-1.5"
                onClick={() => setSimulateOpen(true)}
              >
                <Plus className="h-3.5 w-3.5" />
                Simulate Inbound
              </Button>
            </div>

            <TabsContent value="webhooks" className="px-4 pb-3 max-h-56 overflow-auto">
              <WebhookConfig />
            </TabsContent>

            <TabsContent value="deliveries" className="px-4 pb-3 max-h-56 overflow-auto">
              <DeliveriesPanel deliveries={deliveries} />
            </TabsContent>
          </Tabs>
        </div>
      )}

      {selectedProviderId && (
        <SimulateDialog
          open={simulateOpen}
          onOpenChange={setSimulateOpen}
          providerId={selectedProviderId}
        />
      )}
    </>
  );
}

export { MessageThread };
