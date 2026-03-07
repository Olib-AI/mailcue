import { Paperclip, Shield, Lock } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  formatEmailDate,
  formatEmailAddress,
  extractDisplayName,
  truncate,
} from "@/lib/utils";
import { Avatar } from "@/components/ui/avatar";
import type { EmailSummary } from "@/types/api";

interface EmailItemProps {
  email: EmailSummary;
  isSelected: boolean;
  onSelect: (uid: string) => void;
  isChecked?: boolean;
  onCheckChange?: (uid: string, checked: boolean) => void;
  selectionMode?: boolean;
}

function EmailItem({
  email,
  isSelected,
  onSelect,
  isChecked = false,
  onCheckChange,
  selectionMode = false,
}: EmailItemProps) {
  const fromDisplay = extractDisplayName(email.from_address);

  return (
    <div
      className={cn(
        "flex w-full items-start gap-3 border-b p-3 text-left transition-colors",
        isSelected ? "bg-accent" : "hover:bg-muted/50",
        !email.is_read && "bg-primary/[0.03]"
      )}
    >
      {selectionMode && (
        <label
          className="flex items-center pt-1 shrink-0"
          onClick={(e) => e.stopPropagation()}
        >
          <input
            type="checkbox"
            checked={isChecked}
            onChange={(e) => onCheckChange?.(email.uid, e.target.checked)}
            className="h-4 w-4 rounded border-input accent-primary cursor-pointer"
          />
        </label>
      )}
      <button
        type="button"
        onClick={() => onSelect(email.uid)}
        className="flex flex-1 items-start gap-3 text-left min-w-0"
        aria-current={isSelected ? "true" : undefined}
      >
        <Avatar name={fromDisplay} size="sm" />
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between gap-2">
            <span
              className={cn(
                "text-sm truncate",
                !email.is_read ? "font-semibold" : "font-normal"
              )}
            >
              {formatEmailAddress(email.from_address)}
            </span>
            <span className="text-xs text-muted-foreground whitespace-nowrap shrink-0">
              {formatEmailDate(email.date)}
            </span>
          </div>
          <div className="flex items-center gap-1.5">
            <span
              className={cn(
                "text-sm truncate",
                !email.is_read
                  ? "font-medium text-foreground"
                  : "text-foreground/80"
              )}
            >
              {email.subject || "(no subject)"}
            </span>
            {email.is_signed && (
              <span title="Digitally signed">
                <Shield className="h-3 w-3 text-muted-foreground shrink-0" />
              </span>
            )}
            {email.is_encrypted && (
              <span title="Encrypted">
                <Lock className="h-3 w-3 text-muted-foreground shrink-0" />
              </span>
            )}
            {email.has_attachments && (
              <Paperclip className="h-3 w-3 text-muted-foreground shrink-0" />
            )}
          </div>
          <p className="text-xs text-muted-foreground truncate mt-0.5">
            {truncate(email.preview, 100)}
          </p>
        </div>
      </button>
    </div>
  );
}

export { EmailItem };
