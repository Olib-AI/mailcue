import { useSearchParams } from "react-router-dom";
import { Inbox, Loader2, AlertCircle, RefreshCw } from "lucide-react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { EmailItem } from "./email-item";
import { useEmails } from "@/hooks/use-emails";
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
  const { selectedMailbox, selectedFolder, selectedEmailUid, setSelectedEmailUid } =
    useUIStore();

  const { data, isLoading, isError, error, refetch, isFetching } = useEmails(
    selectedMailbox,
    selectedFolder,
    1,
    search
  );

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

  const emails = data?.emails ?? [];

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
      <div className="flex items-center justify-between border-b px-3 py-2">
        <span className="text-xs text-muted-foreground">
          {data?.total ?? 0} email{(data?.total ?? 0) !== 1 ? "s" : ""}
          {search && ` matching "${search}"`}
        </span>
        {isFetching && !isLoading && (
          <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />
        )}
      </div>

      {/* Email list */}
      <ScrollArea className="flex-1">
        {emails.map((email) => (
          <EmailItem
            key={email.uid}
            email={email}
            isSelected={selectedEmailUid === email.uid}
            onSelect={setSelectedEmailUid}
          />
        ))}

        {/* Load more */}
        {data?.has_more && (
          <div className="p-3 text-center">
            <Button variant="ghost" size="sm" className="text-xs">
              Load more
            </Button>
          </div>
        )}
      </ScrollArea>
    </div>
  );
}

export { EmailList };
