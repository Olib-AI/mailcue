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
} from "lucide-react";
import { toast } from "sonner";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { EmailItem } from "./email-item";
import { useEmails, useBulkDeleteEmails } from "@/hooks/use-emails";
import { useUIStore } from "@/stores/ui-store";

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

function EmailList() {
  const [searchParams] = useSearchParams();
  const search = searchParams.get("search") ?? undefined;
  const {
    selectedMailbox,
    selectedFolder,
    selectedEmailUid,
    setSelectedEmailUid,
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
          // Clear selection for deleted items
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
      {/* List header */}
      <div className="flex items-center justify-between border-b px-3 py-2 gap-2">
        {selectionMode ? (
          <>
            <div className="flex items-center gap-2">
              <Button
                variant="ghost"
                size="sm"
                className="h-7 px-2 text-xs"
                onClick={handleSelectAll}
              >
                {selectedUids.size === emails.length
                  ? "Deselect all"
                  : "Select all"}
              </Button>
              <span className="text-xs text-muted-foreground">
                {selectedUids.size} selected
              </span>
            </div>
            <div className="flex items-center gap-1">
              <Button
                variant="destructive"
                size="sm"
                className="h-7 px-2 text-xs"
                onClick={handleBulkDelete}
                disabled={selectedUids.size === 0 || bulkDelete.isPending}
              >
                {bulkDelete.isPending ? (
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
                onClick={exitSelectionMode}
              >
                <X className="h-3.5 w-3.5" />
              </Button>
            </div>
          </>
        ) : (
          <>
            <span className="text-xs text-muted-foreground">
              {total > emails.length
                ? `Showing ${emails.length} of ${total}`
                : `${total}`}{" "}
              email{total !== 1 ? "s" : ""}
              {search && ` matching "${search}"`}
            </span>
            <div className="flex items-center gap-1">
              {isFetching && !isLoading && (
                <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />
              )}
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7"
                onClick={() => setSelectionMode(true)}
                title="Select emails"
              >
                <CheckSquare className="h-3.5 w-3.5" />
              </Button>
            </div>
          </>
        )}
      </div>

      {/* Search scope indicator */}
      {search && (
        <p className="text-xs text-muted-foreground px-4 py-1.5 border-b bg-muted/30">
          Searching in: {selectedFolder === "INBOX" ? "Inbox" : selectedFolder}
        </p>
      )}

      {/* Email list */}
      <ScrollArea className="flex-1">
        {emails.map((email) => (
          <EmailItem
            key={email.uid}
            email={email}
            isSelected={selectedEmailUid === email.uid}
            onSelect={setSelectedEmailUid}
            selectionMode={selectionMode}
            isChecked={selectedUids.has(email.uid)}
            onCheckChange={handleCheckChange}
          />
        ))}

        {/* Load more */}
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

export { EmailList };
