import {
  Trash2,
  Loader2,
  AlertCircle,
  RefreshCw,
  ChevronDown,
  ChevronUp,
  Mail,
  MailOpen,
  Reply,
  ReplyAll,
  Forward,
  GitCompareArrows,
  Check,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";
import { useState, useCallback } from "react";
import { toast } from "sonner";
import {
  formatFullDate,
  formatEmailAddress,
  extractDisplayName,
} from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Avatar } from "@/components/ui/avatar";
import { EmailRenderer } from "./email-renderer";
import { EmailHeaders } from "./email-headers";
import { EmailAnalysis } from "./email-analysis";
import { AttachmentList } from "./attachment-list";
import { GpgStatusBadge } from "@/components/gpg/gpg-status-badge";
import { useEmail, useDeleteEmail, useToggleReadStatus, useMarkAsSpam, useMarkAsNotSpam } from "@/hooks/use-emails";
import { useUIStore } from "@/stores/ui-store";
import { useCompareStore } from "@/stores/compare-store";

function EmailDetailSkeleton() {
  return (
    <div className="p-6 space-y-4">
      <Skeleton className="h-7 w-3/4" />
      <div className="flex items-center gap-3">
        <Skeleton className="h-9 w-9 rounded-full" />
        <div className="space-y-1.5">
          <Skeleton className="h-4 w-40" />
          <Skeleton className="h-3 w-28" />
        </div>
      </div>
      <Skeleton className="h-9 w-64" />
      <Skeleton className="h-64 w-full" />
    </div>
  );
}

function EmailDetail() {
  const { selectedMailbox, selectedEmailUid, setSelectedEmailUid, selectedFolder, openCompose } =
    useUIStore();
  const { data: email, isLoading, isError, error, refetch } = useEmail(
    selectedMailbox,
    selectedEmailUid,
    selectedFolder
  );
  const deleteEmail = useDeleteEmail();
  const toggleRead = useToggleReadStatus();
  const markAsSpam = useMarkAsSpam();
  const markAsNotSpam = useMarkAsNotSpam();
  const { addEmail, removeEmail, hasEmail } = useCompareStore();
  const isInCompare = hasEmail(selectedMailbox ?? "", selectedEmailUid ?? "");
  const [showAllHeaders, setShowAllHeaders] = useState(false);

  const handleDelete = useCallback(() => {
    if (!selectedMailbox || selectedEmailUid === null) return;
    deleteEmail.mutate(
      { mailbox: selectedMailbox, uid: selectedEmailUid, folder: selectedFolder },
      {
        onSuccess: () => {
          toast.success(selectedFolder.toLowerCase() === "trash" ? "Email permanently deleted" : "Email moved to Trash");
          setSelectedEmailUid(null);
        },
        onError: (err) => {
          toast.error(
            err instanceof Error ? err.message : "Failed to delete email"
          );
        },
      }
    );
  }, [selectedMailbox, selectedEmailUid, selectedFolder, deleteEmail, setSelectedEmailUid]);

  const handleMarkUnread = useCallback(() => {
    if (!selectedMailbox || selectedEmailUid === null) return;
    toggleRead.mutate(
      { mailbox: selectedMailbox, uid: selectedEmailUid, seen: false },
      {
        onSuccess: () => {
          toast.success("Marked as unread");
          setSelectedEmailUid(null);
        },
        onError: (err) => {
          toast.error(
            err instanceof Error ? err.message : "Failed to update read status"
          );
        },
      }
    );
  }, [selectedMailbox, selectedEmailUid, toggleRead, setSelectedEmailUid]);

  const isJunkFolder = selectedFolder === "Junk";

  const handleSpamAction = useCallback(() => {
    if (!selectedMailbox || selectedEmailUid === null) return;
    if (isJunkFolder) {
      markAsNotSpam.mutate(
        { mailbox: selectedMailbox, uid: selectedEmailUid },
        {
          onSuccess: () => {
            toast.success("Moved to Inbox");
            setSelectedEmailUid(null);
          },
          onError: (err) => {
            toast.error(
              err instanceof Error ? err.message : "Failed to mark as not spam"
            );
          },
        }
      );
    } else {
      markAsSpam.mutate(
        { mailbox: selectedMailbox, uid: selectedEmailUid, folder: selectedFolder },
        {
          onSuccess: () => {
            toast.success("Moved to Junk");
            setSelectedEmailUid(null);
          },
          onError: (err) => {
            toast.error(
              err instanceof Error ? err.message : "Failed to mark as spam"
            );
          },
        }
      );
    }
  }, [selectedMailbox, selectedEmailUid, selectedFolder, isJunkFolder, markAsSpam, markAsNotSpam, setSelectedEmailUid]);

  // Empty state
  if (!selectedEmailUid) {
    return (
      <div className="flex h-full items-center justify-center p-8 text-center">
        <div className="space-y-2">
          <Mail className="mx-auto h-12 w-12 text-muted-foreground/50" />
          <p className="text-sm text-muted-foreground">
            Select an email to read
          </p>
        </div>
      </div>
    );
  }

  if (isLoading) {
    return <EmailDetailSkeleton />;
  }

  if (isError || !email) {
    return (
      <div className="flex h-full items-center justify-center p-8 text-center">
        <div className="space-y-3">
          <AlertCircle className="mx-auto h-10 w-10 text-destructive" />
          <p className="text-sm text-destructive">
            {error instanceof Error
              ? error.message
              : "Failed to load email"}
          </p>
          <Button variant="outline" size="sm" onClick={() => void refetch()}>
            <RefreshCw className="mr-2 h-4 w-4" />
            Retry
          </Button>
        </div>
      </div>
    );
  }

  const fromDisplay = email.from_name || extractDisplayName(email.from_address);

  return (
    <ScrollArea className="h-full">
      <div className="p-6">
        {/* Subject */}
        <div className="flex items-start justify-between gap-4 mb-4">
          <div className="space-y-1.5">
            <h1 className="text-xl font-semibold leading-tight">
              {email.subject || "(no subject)"}
            </h1>
            {email.gpg && (email.gpg.is_signed || email.gpg.is_encrypted) && (
              <GpgStatusBadge gpg={email.gpg} />
            )}
          </div>
          <div className="flex items-center gap-1 shrink-0">
            <Button
              variant="ghost"
              size="icon"
              onClick={() => openCompose({ mode: "reply", originalEmail: email })}
              aria-label="Reply"
            >
              <Reply className="h-4 w-4" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              onClick={() => openCompose({ mode: "reply-all", originalEmail: email })}
              aria-label="Reply all"
            >
              <ReplyAll className="h-4 w-4" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              onClick={() => openCompose({ mode: "forward", originalEmail: email })}
              aria-label="Forward"
            >
              <Forward className="h-4 w-4" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              onClick={() => {
                if (!selectedMailbox || !selectedEmailUid) return;
                if (isInCompare) {
                  removeEmail(selectedMailbox, selectedEmailUid);
                } else {
                  addEmail({
                    uid: selectedEmailUid,
                    mailbox: selectedMailbox,
                    folder: selectedFolder,
                    subject: email.subject,
                    from_address: email.from_address,
                  });
                }
              }}
              className={isInCompare ? "text-primary hover:text-primary" : ""}
              aria-label={isInCompare ? "Remove from compare" : "Add to compare"}
            >
              {isInCompare ? (
                <Check className="h-4 w-4" />
              ) : (
                <GitCompareArrows className="h-4 w-4" />
              )}
            </Button>
            <Button
              variant="ghost"
              size="icon"
              onClick={handleMarkUnread}
              disabled={toggleRead.isPending}
              aria-label="Mark as unread"
            >
              {toggleRead.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <MailOpen className="h-4 w-4" />
              )}
            </Button>
            <Button
              variant="ghost"
              size="icon"
              onClick={handleSpamAction}
              disabled={markAsSpam.isPending || markAsNotSpam.isPending}
              className={isJunkFolder ? "text-green-600 hover:text-green-600" : "text-orange-500 hover:text-orange-500"}
              aria-label={isJunkFolder ? "Not spam" : "Mark as spam"}
              title={isJunkFolder ? "Not Spam" : "Mark as Spam"}
            >
              {markAsSpam.isPending || markAsNotSpam.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : isJunkFolder ? (
                <ShieldCheck className="h-4 w-4" />
              ) : (
                <ShieldAlert className="h-4 w-4" />
              )}
            </Button>
            <Button
              variant="ghost"
              size="icon"
              onClick={handleDelete}
              disabled={deleteEmail.isPending}
              className="text-destructive hover:text-destructive"
              aria-label="Delete email"
            >
              {deleteEmail.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Trash2 className="h-4 w-4" />
              )}
            </Button>
          </div>
        </div>

        {/* From / To / Date */}
        <div className="flex items-start gap-3 mb-4">
          <Avatar name={fromDisplay} size="md" />
          <div className="flex-1 min-w-0">
            <div className="flex items-center justify-between gap-2">
              <p className="text-sm font-medium">
                {fromDisplay}
              </p>
              {email.from_name && (
                <p className="text-xs text-muted-foreground">
                  {email.from_address}
                </p>
              )}
              <span className="text-xs text-muted-foreground whitespace-nowrap">
                {formatFullDate(email.date)}
              </span>
            </div>
            <div className="text-xs text-muted-foreground mt-0.5">
              <span>To: </span>
              {email.to_addresses
                .map((a) => formatEmailAddress(a))
                .join(", ")}
            </div>
            {email.cc_addresses && email.cc_addresses.length > 0 && (
              <div className="text-xs text-muted-foreground">
                <span>Cc: </span>
                {email.cc_addresses
                  .map((a) => formatEmailAddress(a))
                  .join(", ")}
              </div>
            )}

            {/* Expand headers toggle */}
            <button
              type="button"
              onClick={() => setShowAllHeaders(!showAllHeaders)}
              className="flex items-center gap-1 text-xs text-primary hover:underline mt-1"
            >
              {showAllHeaders ? (
                <>
                  <ChevronUp className="h-3 w-3" /> Hide details
                </>
              ) : (
                <>
                  <ChevronDown className="h-3 w-3" /> Show details
                </>
              )}
            </button>

            {showAllHeaders && (
              <div className="mt-2 flex flex-wrap gap-1">
                <Badge variant="outline" className="text-xs">
                  UID: {email.uid}
                </Badge>
                {email.message_id && (
                  <Badge variant="outline" className="text-xs">
                    Message-ID: {email.message_id}
                  </Badge>
                )}
              </div>
            )}
          </div>
        </div>

        <Separator className="mb-4" />

        {/* Content Tabs */}
        <Tabs key={email.uid} defaultValue={email.html_body ? "html" : "text"}>
          <TabsList>
            {email.html_body && <TabsTrigger value="html">HTML</TabsTrigger>}
            {email.text_body && (
              <TabsTrigger value="text">Plain Text</TabsTrigger>
            )}
            <TabsTrigger value="headers">Headers</TabsTrigger>
            <TabsTrigger value="analysis">Analysis</TabsTrigger>
            {email.gpg && (email.gpg.is_signed || email.gpg.is_encrypted) && (
              <TabsTrigger value="gpg">GPG</TabsTrigger>
            )}
          </TabsList>

          {email.html_body && (
            <TabsContent value="html">
              <EmailRenderer
                html={email.html_body}
                mailbox={selectedMailbox ?? undefined}
                uid={email.uid}
                attachments={email.attachments}
              />
            </TabsContent>
          )}

          {email.text_body && (
            <TabsContent value="text">
              <pre className="whitespace-pre-wrap font-mono text-sm bg-muted/50 rounded-lg p-4 overflow-auto max-h-[600px]">
                {email.text_body}
              </pre>
            </TabsContent>
          )}

          <TabsContent value="headers">
            <EmailHeaders headers={email.raw_headers} />
          </TabsContent>

          <TabsContent value="analysis">
            <EmailAnalysis headers={email.raw_headers} />
          </TabsContent>

          {email.gpg && (email.gpg.is_signed || email.gpg.is_encrypted) && (
            <TabsContent value="gpg">
              <div className="rounded-lg border p-4 space-y-3">
                {email.gpg.is_signed && (
                  <div className="space-y-2">
                    <h3 className="text-sm font-semibold">Signature</h3>
                    <div className="grid gap-1 text-sm">
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">Status</span>
                        <span className="font-medium">
                          {email.gpg.signature_status ?? "Unknown"}
                        </span>
                      </div>
                      {email.gpg.signer_uid && (
                        <div className="flex justify-between">
                          <span className="text-muted-foreground">
                            Signer
                          </span>
                          <span className="font-mono text-xs">
                            {email.gpg.signer_uid}
                          </span>
                        </div>
                      )}
                      {email.gpg.signer_fingerprint && (
                        <div className="flex justify-between">
                          <span className="text-muted-foreground">
                            Fingerprint
                          </span>
                          <span
                            className="font-mono text-xs truncate ml-4"
                            title={email.gpg.signer_fingerprint}
                          >
                            {email.gpg.signer_fingerprint}
                          </span>
                        </div>
                      )}
                      {email.gpg.signer_key_id && (
                        <div className="flex justify-between">
                          <span className="text-muted-foreground">
                            Key ID
                          </span>
                          <span className="font-mono text-xs">
                            {email.gpg.signer_key_id}
                          </span>
                        </div>
                      )}
                    </div>
                  </div>
                )}
                {email.gpg.is_encrypted && (
                  <div className="space-y-2">
                    <h3 className="text-sm font-semibold">Encryption</h3>
                    <div className="grid gap-1 text-sm">
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">
                          Decrypted
                        </span>
                        <span className="font-medium">
                          {email.gpg.decrypted ? "Yes" : "No"}
                        </span>
                      </div>
                      {email.gpg.encryption_key_ids.length > 0 && (
                        <div>
                          <span className="text-muted-foreground text-sm">
                            Encryption Key IDs
                          </span>
                          <div className="mt-1 flex flex-wrap gap-1">
                            {email.gpg.encryption_key_ids.map((kid) => (
                              <Badge
                                key={kid}
                                variant="outline"
                                className="font-mono text-xs"
                              >
                                {kid}
                              </Badge>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </div>
            </TabsContent>
          )}

        </Tabs>

        {/* Attachments */}
        {email.attachments.length > 0 && (
          <>
            <Separator className="my-4" />
            <AttachmentList
              attachments={email.attachments}
              mailbox={selectedMailbox ?? ""}
              uid={email.uid}
            />
          </>
        )}
      </div>
    </ScrollArea>
  );
}

export { EmailDetail };
