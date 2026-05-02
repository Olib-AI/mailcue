import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ChevronDown,
  ChevronUp,
  Forward,
  Loader2,
  MessageSquare,
  Reply,
  ReplyAll,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { Separator } from "@/components/ui/separator";
import { Avatar } from "@/components/ui/avatar";
import {
  formatEmailDate,
  formatFullDate,
  extractDisplayName,
  truncate,
} from "@/lib/utils";
import { EmailRenderer } from "./email-renderer";
import { AttachmentList } from "./attachment-list";
import { useEmail } from "@/hooks/use-emails";
import { useUIStore } from "@/stores/ui-store";
import type { EmailSummary } from "@/types/api";
import type { ThreadSummary } from "@/hooks/use-email-threads";

interface ThreadDetailProps {
  thread: ThreadSummary;
}

interface ThreadMessageProps {
  email: EmailSummary;
  expanded: boolean;
  onToggle: () => void;
  isLatest: boolean;
}

function ThreadMessage({
  email,
  expanded,
  onToggle,
  isLatest,
}: ThreadMessageProps) {
  const selectedMailbox = useUIStore((s) => s.selectedMailbox);
  const selectedFolder = useUIStore((s) => s.selectedFolder);
  const openCompose = useUIStore((s) => s.openCompose);

  const { data: detail, isLoading, isError, error } = useEmail(
    expanded ? selectedMailbox : null,
    expanded ? email.uid : null,
    selectedFolder
  );

  const fromDisplay =
    email.from_name || extractDisplayName(email.from_address);

  return (
    <div
      className={
        "rounded-lg border bg-background transition-shadow " +
        (expanded ? "shadow-sm" : "")
      }
    >
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-start gap-3 p-3 text-left"
        aria-expanded={expanded}
      >
        <Avatar name={fromDisplay} size="sm" />
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between gap-2">
            <span className="text-sm font-medium truncate">{fromDisplay}</span>
            <span className="text-xs text-muted-foreground whitespace-nowrap shrink-0">
              {expanded ? formatFullDate(email.date) : formatEmailDate(email.date)}
            </span>
          </div>
          {!expanded && (
            <p className="text-xs text-muted-foreground truncate mt-0.5">
              {truncate(email.preview, 140)}
            </p>
          )}
          {expanded && (
            <div className="text-xs text-muted-foreground mt-0.5 truncate">
              To: {email.to_addresses.join(", ")}
            </div>
          )}
        </div>
        {expanded ? (
          <ChevronUp className="h-4 w-4 text-muted-foreground shrink-0" />
        ) : (
          <ChevronDown className="h-4 w-4 text-muted-foreground shrink-0" />
        )}
      </button>

      {expanded && (
        <div className="border-t px-4 pb-4 pt-3">
          {isLoading && (
            <div className="space-y-3">
              <Skeleton className="h-4 w-3/4" />
              <Skeleton className="h-32 w-full" />
            </div>
          )}
          {isError && (
            <p className="text-sm text-destructive">
              {error instanceof Error
                ? error.message
                : "Failed to load message"}
            </p>
          )}
          {detail && (
            <>
              {detail.html_body ? (
                <EmailRenderer
                  html={detail.html_body}
                  mailbox={selectedMailbox ?? undefined}
                  uid={detail.uid}
                  attachments={detail.attachments}
                />
              ) : (
                <pre className="whitespace-pre-wrap font-mono text-sm bg-muted/50 rounded-lg p-4 overflow-auto max-h-[600px]">
                  {detail.text_body ?? ""}
                </pre>
              )}

              {detail.attachments.length > 0 && (
                <>
                  <Separator className="my-4" />
                  <AttachmentList
                    attachments={detail.attachments}
                    mailbox={selectedMailbox ?? ""}
                    uid={detail.uid}
                  />
                </>
              )}

              {isLatest && (
                <div className="flex items-center gap-1 mt-4">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() =>
                      openCompose({ mode: "reply", originalEmail: detail })
                    }
                  >
                    <Reply className="h-4 w-4" />
                    Reply
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() =>
                      openCompose({ mode: "reply-all", originalEmail: detail })
                    }
                  >
                    <ReplyAll className="h-4 w-4" />
                    Reply all
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() =>
                      openCompose({ mode: "forward", originalEmail: detail })
                    }
                  >
                    <Forward className="h-4 w-4" />
                    Forward
                  </Button>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

function ThreadDetail({ thread }: ThreadDetailProps) {
  const subject = thread.latest.subject || "(no subject)";
  const latestUid = thread.latest.uid;

  const initialExpanded = useMemo(() => {
    const set = new Set<string>();
    set.add(latestUid);
    // Expanding all unread drafts may surprise users — only the latest is
    // expanded by default, matching Gmail's behavior.
    return set;
  }, [latestUid]);

  const [expanded, setExpanded] = useState<Set<string>>(initialExpanded);

  // Reset expansion when the thread changes (avoids stale state when the user
  // hops between threads).
  useEffect(() => {
    setExpanded(new Set([latestUid]));
  }, [latestUid, thread.thread_id]);

  const allExpanded = expanded.size === thread.emails.length;

  const toggle = useCallback((uid: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(uid)) {
        next.delete(uid);
      } else {
        next.add(uid);
      }
      return next;
    });
  }, []);

  const toggleAll = useCallback(() => {
    setExpanded((prev) => {
      if (prev.size === thread.emails.length) {
        return new Set([latestUid]);
      }
      return new Set(thread.emails.map((e) => e.uid));
    });
  }, [thread.emails, latestUid]);

  return (
    <ScrollArea className="h-full">
      <div className="p-6 space-y-3">
        <div className="flex items-start justify-between gap-4">
          <h1 className="text-xl font-semibold leading-tight">{subject}</h1>
        </div>

        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <MessageSquare className="h-3.5 w-3.5" />
          <span>
            {thread.count} message{thread.count !== 1 ? "s" : ""}
          </span>
          {thread.count > 1 && (
            <Button
              variant="ghost"
              size="sm"
              className="h-7 px-2 text-xs"
              onClick={toggleAll}
            >
              {allExpanded ? "Collapse all" : "Expand all"}
            </Button>
          )}
        </div>

        <Separator />

        <div className="space-y-2">
          {thread.emails.map((email) => (
            <ThreadMessage
              key={`${email.mailbox}:${email.uid}`}
              email={email}
              expanded={expanded.has(email.uid)}
              onToggle={() => toggle(email.uid)}
              isLatest={email.uid === latestUid}
            />
          ))}
        </div>
      </div>
    </ScrollArea>
  );
}

function ThreadDetailSkeleton() {
  return (
    <div className="p-6 space-y-4">
      <Skeleton className="h-7 w-3/4" />
      <Skeleton className="h-4 w-32" />
      <div className="space-y-2">
        {Array.from({ length: 3 }, (_, i) => (
          <Skeleton key={i} className="h-16 w-full rounded-lg" />
        ))}
      </div>
    </div>
  );
}

function ThreadDetailLoading() {
  return (
    <div className="flex h-full items-center justify-center">
      <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
    </div>
  );
}

export { ThreadDetail, ThreadDetailSkeleton, ThreadDetailLoading };
