import { Download, FileText, Image, File } from "lucide-react";
import { Button } from "@/components/ui/button";
import { formatFileSize } from "@/lib/utils";
import type { EmailAttachment } from "@/types/api";

interface AttachmentListProps {
  attachments: EmailAttachment[];
  mailbox: string;
  uid: string;
}

function getAttachmentIcon(contentType: string) {
  if (contentType.startsWith("image/")) return Image;
  if (contentType.includes("pdf") || contentType.startsWith("text/"))
    return FileText;
  return File;
}

function AttachmentList({ attachments, mailbox, uid }: AttachmentListProps) {
  if (attachments.length === 0) return null;

  const handleDownload = (partId: string) => {
    const url = `/api/v1/mailboxes/${encodeURIComponent(mailbox)}/emails/${encodeURIComponent(uid)}/attachments/${encodeURIComponent(partId)}`;
    window.open(url, "_blank");
  };

  return (
    <div className="border-t p-4">
      <h4 className="text-sm font-medium mb-3">
        Attachments ({attachments.length})
      </h4>
      <div className="flex flex-wrap gap-2">
        {attachments.map((attachment) => {
          const Icon = getAttachmentIcon(attachment.content_type);
          return (
            <div
              key={attachment.filename}
              className="flex items-center gap-2 rounded-lg border bg-muted/30 px-3 py-2 text-sm"
            >
              <Icon className="h-4 w-4 text-muted-foreground shrink-0" />
              <div className="min-w-0">
                <p className="font-medium truncate max-w-[150px]">
                  {attachment.filename}
                </p>
                <p className="text-xs text-muted-foreground">
                  {formatFileSize(attachment.size)}
                </p>
              </div>
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7 shrink-0"
                onClick={() => handleDownload(attachment.part_id)}
                aria-label={`Download ${attachment.filename}`}
              >
                <Download className="h-3.5 w-3.5" />
              </Button>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export { AttachmentList };
