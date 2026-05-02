import { ArrowLeft } from "lucide-react";
import { EmailList } from "@/components/email/email-list";
import { EmailDetail } from "@/components/email/email-detail";
import { ThreadDetail } from "@/components/email/thread-detail";
import { Separator } from "@/components/ui/separator";
import { Button } from "@/components/ui/button";
import { useUIStore } from "@/stores/ui-store";
import { useEmailThreads } from "@/hooks/use-email-threads";

function ThreadOrEmailDetail() {
  const selectedMailbox = useUIStore((s) => s.selectedMailbox);
  const selectedFolder = useUIStore((s) => s.selectedFolder);
  const selectedThreadId = useUIStore((s) => s.selectedThreadId);
  const mailViewMode = useUIStore((s) => s.mailViewMode);

  // Only fetch threads when we actually need to resolve a thread; the underlying
  // query is already in-flight from the list, so this is a cache hit.
  const enabled = mailViewMode === "conversations" && selectedThreadId !== null;
  const { data } = useEmailThreads(
    enabled ? selectedMailbox : null,
    selectedFolder
  );

  const thread =
    enabled && data
      ? data.threads.find((t) => t.thread_id === selectedThreadId)
      : undefined;

  if (thread && thread.count > 1) {
    return <ThreadDetail thread={thread} />;
  }

  return <EmailDetail />;
}

function MailPage() {
  const selectedEmailUid = useUIStore((s) => s.selectedEmailUid);
  const selectedThreadId = useUIStore((s) => s.selectedThreadId);
  const setSelectedEmailUid = useUIStore((s) => s.setSelectedEmailUid);
  const setSelectedThreadId = useUIStore((s) => s.setSelectedThreadId);
  const hasSelection = selectedEmailUid !== null || selectedThreadId !== null;

  const clearSelection = () => {
    setSelectedEmailUid(null);
    setSelectedThreadId(null);
  };

  return (
    <div className="flex h-full">
      {/* Email List Panel — hidden on mobile when an email is selected */}
      <div
        className={`w-full md:w-80 md:min-w-[280px] md:max-w-[400px] flex-shrink-0 border-r flex flex-col overflow-hidden ${
          hasSelection ? "hidden md:flex" : "flex"
        }`}
      >
        <EmailList />
      </div>

      <Separator orientation="vertical" className="hidden md:block" />

      {/* Email Detail Panel — hidden on mobile when no email is selected */}
      <div
        className={`flex-1 overflow-hidden flex-col ${
          hasSelection ? "flex" : "hidden md:flex"
        }`}
      >
        {/* Mobile back button */}
        {hasSelection && (
          <div className="flex items-center border-b px-2 py-1.5 md:hidden">
            <Button
              variant="ghost"
              size="sm"
              className="gap-1.5"
              onClick={clearSelection}
            >
              <ArrowLeft className="h-4 w-4" />
              Back
            </Button>
          </div>
        )}
        <div className="flex-1 overflow-hidden">
          <ThreadOrEmailDetail />
        </div>
      </div>
    </div>
  );
}

export { MailPage };
