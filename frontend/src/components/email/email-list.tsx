import { useState, useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import {
  Inbox,
  Loader2,
  AlertCircle,
  RefreshCw,
  Trash2,
  CheckSquare,
  X,
  MessagesSquare,
  Mail as MailIcon,
} from "lucide-react";
import { toast } from "sonner";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { EmailItem } from "./email-item";
import { ThreadItem } from "./thread-item";
import { useEmails, useBulkDeleteEmails } from "@/hooks/use-emails";
import { useEmailThreads } from "@/hooks/use-email-threads";
import { useUIStore } from "@/stores/ui-store";
import type { ThreadSummary } from "@/hooks/use-email-threads";

function EmailListSkeleton() {
  return (
    <div className="space-y-0">
      {Array.from({ length: 8 }, (_, i) => (
        <div key={i} className="flex items-start gap-3 border-b p-3">
          <Skeleton className="h-7 w-7 rounded-full shrink-0" />
          <div className="flex-1 space-y-2">
            <div className="flex items-center justify-between">
              <Skeleton className="h-4 w-32" />
              <Skeleton className="h-3 w-12" />
            </div>
            <Skeleton className="h-4 w-48" />
            <Skeleton className="h-3 w-64" />
          </div>
        </div>
      ))}
    </div>
  );
}

function ViewModeToggle() {
  const mode = useUIStore((s) => s.mailViewMode);
  const setMode = useUIStore((s) => s.setMailViewMode);

  return (
    <div
      role="group"
      aria-label="Mail view mode"
      className="inline-flex items-center rounded-md border bg-background p-0.5"
    >
      <button
        type="button"
        onClick={() => setMode("conversations")}
        className={cn(
          "inline-flex items-center gap-1 rounded px-2 py-0.5 text-[11px] font-medium transition-colors",
          mode === "conversations"
            ? "bg-accent text-foreground"
            : "text-muted-foreground hover:text-foreground"
        )}
        title="Group emails into conversations"
        aria-pressed={mode === "conversations"}
      >
        <MessagesSquare className="h-3 w-3" />
        Conversations
      </button>
      <button
        type="button"
        onClick={() => setMode("messages")}
        className={cn(
          "inline-flex items-center gap-1 rounded px-2 py-0.5 text-[11px] font-medium transition-colors",
          mode === "messages"
            ? "bg-accent text-foreground"
            : "text-muted-foreground hover:text-foreground"
        )}
        title="Show every email as a separate row"
        aria-pressed={mode === "messages"}
      >
        <MailIcon className="h-3 w-3" />
        Messages
      </button>
    </div>
  );
}

function FlatEmailList() {
  const [searchParams] = useSearchParams();
  const search = searchParams.get("search") ?? undefined;
  const {
    selectedMailbox,
    selectedFolder,
    selectedEmailUid,
    setSelectedEmailUid,
    setSelectedThreadId,
  } = useUIStore();

  const {
    data,
    isLoading,
    isError,
    error,
    refetch,
    isFetching,
    hasNextPage,
    fetchNextPage,
    isFetchingNextPage,
  } = useEmails(selectedMailbox, selectedFolder, search);

  const [selectionMode, setSelectionMode] = useState(false);
  const [selectedUids, setSelectedUids] = useState<Set<string>>(new Set());
  const bulkDelete = useBulkDeleteEmails();

  const emails = useMemo(
    () => data?.pages.flatMap((page) => page.emails) ?? [],
    [data?.pages]
  );

  const total = data?.pages[0]?.total ?? 0;

  const handleCheckChange = useCallback((uid: string, checked: boolean) => {
    setSelectedUids((prev) => {
      const next = new Set(prev);
      if (checked) {
        next.add(uid);
      } else {
        next.delete(uid);
      }
      return next;
    });
  }, []);

  const handleSelectAll = useCallback(() => {
    if (selectedUids.size === emails.length) {
      setSelectedUids(new Set());
    } else {
      setSelectedUids(new Set(emails.map((e) => e.uid)));
    }
  }, [emails, selectedUids.size]);

  const exitSelectionMode = useCallback(() => {
    setSelectionMode(false);
    setSelectedUids(new Set());
  }, []);

  const handleBulkDelete = useCallback(() => {
    if (!selectedMailbox || selectedUids.size === 0) return;
    const uids = Array.from(selectedUids);
    bulkDelete.mutate(
      { mailbox: selectedMailbox, uids, folder: selectedFolder },
      {
        onSuccess: (result) => {
          toast.success(
            `${result.deleted} email${result.deleted !== 1 ? "s" : ""} deleted${result.failed > 0 ? `, ${result.failed} failed` : ""}`
          );
          if (selectedEmailUid && selectedUids.has(selectedEmailUid)) {
            setSelectedEmailUid(null);
          }
          exitSelectionMode();
        },
        onError: (err) => {
          toast.error(
            err instanceof Error ? err.message : "Failed to delete emails"
          );
        },
      }
    );
  }, [
    selectedMailbox,
    selectedUids,
    selectedFolder,
    selectedEmailUid,
    bulkDelete,
    setSelectedEmailUid,
    exitSelectionMode,
  ]);

  const handleSelectEmail = useCallback(
    (uid: string) => {
      setSelectedThreadId(null);
      setSelectedEmailUid(uid);
    },
    [setSelectedEmailUid, setSelectedThreadId]
  );

  if (isLoading) {
    return <EmailListSkeleton />;
  }

  if (isError) {
    return (
      <div className="flex flex-1 items-center justify-center p-8 text-center">
        <div className="space-y-3">
          <AlertCircle className="mx-auto h-10 w-10 text-destructive" />
          <p className="text-sm text-destructive">
            {error instanceof Error ? error.message : "Failed to load emails"}
          </p>
          <Button variant="outline" size="sm" onClick={() => void refetch()}>
            <RefreshCw className="mr-2 h-4 w-4" />
            Retry
          </Button>
        </div>
      </div>
    );
  }

  if (emails.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center p-8 text-center">
        <div className="space-y-2">
          <Inbox className="mx-auto h-10 w-10 text-muted-foreground" />
          <p className="text-sm font-medium text-muted-foreground">
            {search ? "No emails match your search" : "No emails yet"}
          </p>
          <p className="text-xs text-muted-foreground">
            {search
              ? "Try different search terms"
              : "Emails sent to this mailbox will appear here"}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      <ListHeader
        leftLabel={
          total > emails.length
            ? `Showing ${emails.length} of ${total}`
            : `${total}`
        }
        countLabel={`email${total !== 1 ? "s" : ""}`}
        search={search}
        isFetching={isFetching && !isLoading}
        selectionMode={selectionMode}
        selectedCount={selectedUids.size}
        totalCount={emails.length}
        onSelectAll={handleSelectAll}
        onEnterSelection={() => setSelectionMode(true)}
        onExitSelection={exitSelectionMode}
        onBulkDelete={handleBulkDelete}
        bulkPending={bulkDelete.isPending}
      />

      {search && (
        <p className="text-xs text-muted-foreground px-4 py-1.5 border-b bg-muted/30">
          Searching in: {selectedFolder === "INBOX" ? "Inbox" : selectedFolder}
        </p>
      )}

      <ScrollArea className="flex-1">
        {emails.map((email) => (
          <EmailItem
            key={email.uid}
            email={email}
            isSelected={selectedEmailUid === email.uid}
            onSelect={handleSelectEmail}
            selectionMode={selectionMode}
            isChecked={selectedUids.has(email.uid)}
            onCheckChange={handleCheckChange}
          />
        ))}

        {hasNextPage && (
          <div className="p-3 text-center">
            <Button
              variant="ghost"
              size="sm"
              className="text-xs"
              onClick={() => void fetchNextPage()}
              disabled={isFetchingNextPage}
            >
              {isFetchingNextPage ? (
                <>
                  <Loader2 className="mr-1.5 h-3 w-3 animate-spin" />
                  Loading...
                </>
              ) : (
                `Load more (${emails.length} of ${total})`
              )}
            </Button>
          </div>
        )}
      </ScrollArea>
    </div>
  );
}

function ConversationList() {
  const [searchParams] = useSearchParams();
  const search = searchParams.get("search") ?? undefined;
  const {
    selectedMailbox,
    selectedFolder,
    selectedEmailUid,
    selectedThreadId,
    setSelectedEmailUid,
    setSelectedThreadId,
  } = useUIStore();

  const {
    data,
    isLoading,
    isError,
    error,
    refetch,
    isFetching,
    hasNextPage,
    fetchNextPage,
    isFetchingNextPage,
  } = useEmailThreads(selectedMailbox, selectedFolder, search);

  const [selectionMode, setSelectionMode] = useState(false);
  const [selectedThreadKeys, setSelectedThreadKeys] = useState<Set<string>>(
    new Set()
  );
  const bulkDelete = useBulkDeleteEmails();

  const threads = useMemo(() => data?.threads ?? [], [data?.threads]);
  const total = data?.total ?? 0;
  const loaded = data?.loadedEmailCount ?? 0;

  const handleSelectThread = useCallback(
    (thread: ThreadSummary) => {
      if (thread.count > 1) {
        setSelectedThreadId(thread.thread_id);
        setSelectedEmailUid(thread.latest.uid);
      } else {
        // Single-message threads behave exactly like the flat view.
        setSelectedThreadId(null);
        setSelectedEmailUid(thread.latest.uid);
      }
    },
    [setSelectedEmailUid, setSelectedThreadId]
  );

  const handleCheckChange = useCallback((uid: string, checked: boolean) => {
    // The thread row's checkbox uses the latest email's uid as a key — but for
    // bulk delete we must capture every uid in the thread. Resolve via the
    // thread object on submit.
    setSelectedThreadKeys((prev) => {
      const next = new Set(prev);
      if (checked) {
        next.add(uid);
      } else {
        next.delete(uid);
      }
      return next;
    });
  }, []);

  const handleSelectAll = useCallback(() => {
    if (selectedThreadKeys.size === threads.length) {
      setSelectedThreadKeys(new Set());
    } else {
      setSelectedThreadKeys(new Set(threads.map((t) => t.latest.uid)));
    }
  }, [threads, selectedThreadKeys.size]);

  const exitSelectionMode = useCallback(() => {
    setSelectionMode(false);
    setSelectedThreadKeys(new Set());
  }, []);

  const handleBulkDelete = useCallback(() => {
    if (!selectedMailbox || selectedThreadKeys.size === 0) return;
    const uids: string[] = [];
    for (const thread of threads) {
      if (selectedThreadKeys.has(thread.latest.uid)) {
        for (const e of thread.emails) uids.push(e.uid);
      }
    }
    if (uids.length === 0) return;

    bulkDelete.mutate(
      { mailbox: selectedMailbox, uids, folder: selectedFolder },
      {
        onSuccess: (result) => {
          toast.success(
            `${result.deleted} email${result.deleted !== 1 ? "s" : ""} deleted${result.failed > 0 ? `, ${result.failed} failed` : ""}`
          );
          if (selectedEmailUid && uids.includes(selectedEmailUid)) {
            setSelectedEmailUid(null);
            setSelectedThreadId(null);
          }
          exitSelectionMode();
        },
        onError: (err) => {
          toast.error(
            err instanceof Error ? err.message : "Failed to delete emails"
          );
        },
      }
    );
  }, [
    selectedMailbox,
    selectedThreadKeys,
    threads,
    selectedFolder,
    selectedEmailUid,
    bulkDelete,
    setSelectedEmailUid,
    setSelectedThreadId,
    exitSelectionMode,
  ]);

  if (isLoading) {
    return <EmailListSkeleton />;
  }

  if (isError) {
    return (
      <div className="flex flex-1 items-center justify-center p-8 text-center">
        <div className="space-y-3">
          <AlertCircle className="mx-auto h-10 w-10 text-destructive" />
          <p className="text-sm text-destructive">
            {error instanceof Error ? error.message : "Failed to load emails"}
          </p>
          <Button variant="outline" size="sm" onClick={() => void refetch()}>
            <RefreshCw className="mr-2 h-4 w-4" />
            Retry
          </Button>
        </div>
      </div>
    );
  }

  if (threads.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center p-8 text-center">
        <div className="space-y-2">
          <Inbox className="mx-auto h-10 w-10 text-muted-foreground" />
          <p className="text-sm font-medium text-muted-foreground">
            {search ? "No conversations match your search" : "No conversations yet"}
          </p>
          <p className="text-xs text-muted-foreground">
            {search
              ? "Try different search terms"
              : "Emails sent to this mailbox will appear here"}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      <ListHeader
        leftLabel={
          total > loaded
            ? `Showing ${threads.length} thread${threads.length !== 1 ? "s" : ""} (${loaded} of ${total} emails)`
            : `${threads.length} thread${threads.length !== 1 ? "s" : ""}`
        }
        countLabel=""
        search={search}
        isFetching={isFetching && !isLoading}
        selectionMode={selectionMode}
        selectedCount={selectedThreadKeys.size}
        totalCount={threads.length}
        onSelectAll={handleSelectAll}
        onEnterSelection={() => setSelectionMode(true)}
        onExitSelection={exitSelectionMode}
        onBulkDelete={handleBulkDelete}
        bulkPending={bulkDelete.isPending}
      />

      {search && (
        <p className="text-xs text-muted-foreground px-4 py-1.5 border-b bg-muted/30">
          Searching in: {selectedFolder === "INBOX" ? "Inbox" : selectedFolder}
        </p>
      )}

      <ScrollArea className="flex-1">
        {threads.map((thread) => {
          const isThreadSelected =
            thread.count > 1
              ? selectedThreadId === thread.thread_id
              : selectedEmailUid === thread.latest.uid;
          return (
            <ThreadItem
              key={thread.thread_id}
              thread={thread}
              isSelected={isThreadSelected}
              onSelect={handleSelectThread}
              selectionMode={selectionMode}
              isChecked={selectedThreadKeys.has(thread.latest.uid)}
              onCheckChange={handleCheckChange}
            />
          );
        })}

        {hasNextPage && (
          <div className="p-3 text-center">
            <Button
              variant="ghost"
              size="sm"
              className="text-xs"
              onClick={() => void fetchNextPage()}
              disabled={isFetchingNextPage}
            >
              {isFetchingNextPage ? (
                <>
                  <Loader2 className="mr-1.5 h-3 w-3 animate-spin" />
                  Loading...
                </>
              ) : (
                `Load more (${loaded} of ${total})`
              )}
            </Button>
          </div>
        )}
      </ScrollArea>
    </div>
  );
}

interface ListHeaderProps {
  leftLabel: string;
  countLabel: string;
  search: string | undefined;
  isFetching: boolean;
  selectionMode: boolean;
  selectedCount: number;
  totalCount: number;
  onSelectAll: () => void;
  onEnterSelection: () => void;
  onExitSelection: () => void;
  onBulkDelete: () => void;
  bulkPending: boolean;
}

function ListHeader({
  leftLabel,
  countLabel,
  search,
  isFetching,
  selectionMode,
  selectedCount,
  totalCount,
  onSelectAll,
  onEnterSelection,
  onExitSelection,
  onBulkDelete,
  bulkPending,
}: ListHeaderProps) {
  return (
    <div className="flex flex-col border-b">
      <div className="flex items-center justify-between px-3 py-2 gap-2">
        {selectionMode ? (
          <>
            <div className="flex items-center gap-2">
              <Button
                variant="ghost"
                size="sm"
                className="h-7 px-2 text-xs"
                onClick={onSelectAll}
              >
                {selectedCount === totalCount ? "Deselect all" : "Select all"}
              </Button>
              <span className="text-xs text-muted-foreground">
                {selectedCount} selected
              </span>
            </div>
            <div className="flex items-center gap-1">
              <Button
                variant="destructive"
                size="sm"
                className="h-7 px-2 text-xs"
                onClick={onBulkDelete}
                disabled={selectedCount === 0 || bulkPending}
              >
                {bulkPending ? (
                  <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                ) : (
                  <Trash2 className="mr-1 h-3 w-3" />
                )}
                Delete
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7"
                onClick={onExitSelection}
              >
                <X className="h-3.5 w-3.5" />
              </Button>
            </div>
          </>
        ) : (
          <>
            <span className="text-xs text-muted-foreground truncate">
              {leftLabel}
              {countLabel ? ` ${countLabel}` : ""}
              {search && ` matching "${search}"`}
            </span>
            <div className="flex items-center gap-1">
              {isFetching && (
                <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />
              )}
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7"
                onClick={onEnterSelection}
                title="Select emails"
              >
                <CheckSquare className="h-3.5 w-3.5" />
              </Button>
            </div>
          </>
        )}
      </div>
      {!selectionMode && (
        <div className="flex items-center justify-end px-3 pb-2">
          <ViewModeToggle />
        </div>
      )}
    </div>
  );
}

function EmailList() {
  const selectedMailbox = useUIStore((s) => s.selectedMailbox);
  const mailViewMode = useUIStore((s) => s.mailViewMode);

  if (!selectedMailbox) {
    return (
      <div className="flex flex-1 items-center justify-center p-8 text-center">
        <div className="space-y-2">
          <Inbox className="mx-auto h-10 w-10 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">
            Select a mailbox to view emails
          </p>
        </div>
      </div>
    );
  }

  return mailViewMode === "conversations" ? (
    <ConversationList />
  ) : (
    <FlatEmailList />
  );
}

export { EmailList };
