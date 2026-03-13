import React, { useState } from "react";
import { X, Copy, Check, ArrowDownLeft, ArrowUpRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useSandboxStore } from "@/stores/sandbox-store";
import type { SandboxMessage } from "@/types/sandbox";

// ---------------------------------------------------------------------------
// JsonView - syntax-highlighted JSON renderer
// ---------------------------------------------------------------------------

function renderJsonValue(value: unknown, indent: number): React.ReactNode[] {
  if (value === null) {
    return [<span className="text-purple-600 dark:text-purple-400">null</span>];
  }

  if (typeof value === "boolean") {
    return [
      <span className="text-purple-600 dark:text-purple-400">
        {String(value)}
      </span>,
    ];
  }

  if (typeof value === "number") {
    return [
      <span className="text-amber-600 dark:text-amber-400">{value}</span>,
    ];
  }

  if (typeof value === "string") {
    return [
      <span className="text-green-600 dark:text-green-400">
        &quot;{value}&quot;
      </span>,
    ];
  }

  if (Array.isArray(value)) {
    if (value.length === 0) {
      return [<span>{"[]"}</span>];
    }
    const elements: React.ReactNode[] = [];
    elements.push(<span>{"[\n"}</span>);
    value.forEach((item, i) => {
      const pad = "  ".repeat(indent + 1);
      const trailing = i < value.length - 1 ? ",\n" : "\n";
      elements.push(
        <span key={`arr-${indent}-${i}`}>
          {pad}
          {renderJsonValue(item, indent + 1)}
          {trailing}
        </span>
      );
    });
    elements.push(<span>{"  ".repeat(indent)}]</span>);
    return elements;
  }

  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>);
    if (entries.length === 0) {
      return [<span>{"{}"}</span>];
    }
    const elements: React.ReactNode[] = [];
    elements.push(<span>{"{\n"}</span>);
    entries.forEach(([key, val], i) => {
      const pad = "  ".repeat(indent + 1);
      const trailing = i < entries.length - 1 ? ",\n" : "\n";
      elements.push(
        <span key={`obj-${indent}-${key}`}>
          {pad}
          <span className="text-blue-600 dark:text-blue-400">
            &quot;{key}&quot;
          </span>
          {": "}
          {renderJsonValue(val, indent + 1)}
          {trailing}
        </span>
      );
    });
    elements.push(<span>{"  ".repeat(indent)}</span>);
    elements.push(<span>{"}"}</span>);
    return elements;
  }

  return [<span>{String(value)}</span>];
}

interface JsonViewProps {
  data: unknown;
}

function JsonView({ data }: JsonViewProps) {
  return (
    <pre className="text-[11px] leading-relaxed font-mono whitespace-pre-wrap break-all">
      {renderJsonValue(data, 0)}
    </pre>
  );
}

// ---------------------------------------------------------------------------
// CopyJsonButton
// ---------------------------------------------------------------------------

function CopyJsonButton({ data }: { data: unknown }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    const text = JSON.stringify(data, null, 2);
    void navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  return (
    <Button
      variant="ghost"
      size="sm"
      className="h-7 gap-1 text-xs"
      onClick={handleCopy}
    >
      {copied ? (
        <>
          <Check className="h-3 w-3 text-green-500" />
          Copied
        </>
      ) : (
        <>
          <Copy className="h-3 w-3" />
          Copy
        </>
      )}
    </Button>
  );
}

// ---------------------------------------------------------------------------
// JsonBlock - a JSON payload section with copy button and empty state
// ---------------------------------------------------------------------------

function JsonBlock({ data, label }: { data: unknown; label: string }) {
  const isEmpty =
    data === null ||
    data === undefined ||
    (typeof data === "object" && Object.keys(data as Record<string, unknown>).length === 0);

  return (
    <div className="rounded-md border bg-muted/50">
      <div className="flex items-center justify-between px-3 py-1.5 border-b bg-muted/30">
        <span className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
          {label}
        </span>
        {!isEmpty && <CopyJsonButton data={data} />}
      </div>
      <div className="p-3 max-h-[30vh] overflow-auto">
        {isEmpty ? (
          <p className="text-xs text-muted-foreground italic">
            No data captured
          </p>
        ) : (
          <JsonView data={data} />
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// RequestInspector - main panel
// ---------------------------------------------------------------------------

interface RequestInspectorProps {
  messages: SandboxMessage[];
}

function formatTimestamp(dateString: string): string {
  const date = new Date(dateString);
  return date.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
    hour12: true,
  });
}

function RequestInspector({ messages }: RequestInspectorProps) {
  const { inspectedMessageId, setInspectedMessageId } = useSandboxStore();

  const message = messages.find((m) => m.id === inspectedMessageId);

  if (!message) {
    return null;
  }

  const isInbound = message.direction === "inbound";
  const summary =
    message.content.length > 60
      ? message.content.slice(0, 57) + "..."
      : message.content;

  return (
    <div className="border-t shrink-0 flex flex-col max-h-[50vh]">
      {/* Inspector header bar */}
      <div className="flex items-center gap-2 px-4 py-2 bg-muted/40 border-b shrink-0">
        <Badge
          variant={isInbound ? "secondary" : "default"}
          className="text-[10px] px-1.5 py-0 gap-1 shrink-0"
        >
          {isInbound ? (
            <ArrowDownLeft className="h-2.5 w-2.5" />
          ) : (
            <ArrowUpRight className="h-2.5 w-2.5" />
          )}
          {message.direction}
        </Badge>
        <span className="text-xs font-medium truncate">
          {message.sender}
        </span>
        <span className="text-xs text-muted-foreground truncate hidden sm:inline">
          &mdash; {summary}
        </span>
        <Button
          variant="ghost"
          size="icon"
          className="h-6 w-6 ml-auto shrink-0"
          onClick={() => setInspectedMessageId(null)}
        >
          <X className="h-3.5 w-3.5" />
        </Button>
      </div>

      {/* Message metadata */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-2 text-xs border-b shrink-0">
        <div>
          <span className="text-muted-foreground">Timestamp: </span>
          <span className="font-mono">
            {formatTimestamp(message.created_at)}
          </span>
        </div>
        <div>
          <span className="text-muted-foreground">Content type: </span>
          <Badge variant="outline" className="text-[10px] px-1.5 py-0">
            {message.content_type}
          </Badge>
        </div>
        {message.external_id && (
          <div>
            <span className="text-muted-foreground">External ID: </span>
            <span className="font-mono">{message.external_id}</span>
          </div>
        )}
        <div>
          <span className="text-muted-foreground">Message ID: </span>
          <span className="font-mono text-[10px]">{message.id}</span>
        </div>
      </div>

      {/* Request / Response tabs */}
      <Tabs defaultValue="request" className="flex-1 flex flex-col min-h-0">
        <TabsList className="mx-4 mt-2 w-fit">
          <TabsTrigger value="request">Request</TabsTrigger>
          <TabsTrigger value="response">Response</TabsTrigger>
        </TabsList>

        <TabsContent value="request" className="flex-1 min-h-0 mt-0">
          <ScrollArea className="h-full px-4 pb-3">
            <div className="py-2">
              <JsonBlock data={message.raw_request} label="Raw Request Payload" />
            </div>
          </ScrollArea>
        </TabsContent>

        <TabsContent value="response" className="flex-1 min-h-0 mt-0">
          <ScrollArea className="h-full px-4 pb-3">
            <div className="py-2">
              <JsonBlock data={message.raw_response} label="Raw Response Payload" />
            </div>
          </ScrollArea>
        </TabsContent>
      </Tabs>
    </div>
  );
}

export { RequestInspector, JsonView, JsonBlock, CopyJsonButton };
