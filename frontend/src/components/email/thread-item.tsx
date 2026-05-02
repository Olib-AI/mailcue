import { Paperclip, Shield, Lock, ShieldAlert } from "lucide-react";
import { cn, formatEmailDate, extractDisplayName, truncate } from "@/lib/utils";
import { Avatar } from "@/components/ui/avatar";
import { useUIStore } from "@/stores/ui-store";
import type { ThreadSummary } from "@/hooks/use-email-threads";

interface ThreadItemProps {
  thread: ThreadSummary;
  isSelected: boolean;
  onSelect: (thread: ThreadSummary) => void;
  isChecked?: boolean;
  onCheckChange?: (uid: string, checked: boolean) => void;
  selectionMode?: boolean;
}

const SUBJECT_PREFIX_RE = /^\s*(?:re|fwd?|aw|sv)\s*:\s*/i;

/**
 * Drop a single leading `Re:` / `Fwd:` / `Fw:` / `Aw:` / `Sv:` for visual
 * cleanliness without losing data — the raw subject is still surfaced via the
 * row's `title` attribute.
 */
function stripSubjectPrefix(subject: string): string {
  let next = subject;
  // Strip up to a couple of stacked prefixes ("Re: Fwd: ...")
  for (let i = 0; i < 4; i++) {
    const replaced = next.replace(SUBJECT_PREFIX_RE, "");
    if (replaced === next) break;
    next = replaced;
  }
  return next;
}

/**
 * Build a Gmail-style participant line. The latest email's sender comes first;
 * older participants follow. After three names we collapse to "+N".
 */
function buildParticipantSummary(
  thread: ThreadSummary,
  selfMailbox: string | null
): string {
  const orderedLatestFirst = [...thread.emails].reverse();
  const seen = new Set<string>();
  const names: string[] = [];

  for (const email of orderedLatestFirst) {
    const isSelf =
      selfMailbox !== null &&
      email.from_address.toLowerCase().includes(selfMailbox.toLowerCase());
    const display = isSelf
      ? "You"
      : email.from_name || extractDisplayName(email.from_address);
    const key = isSelf ? "__self__" : display.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    names.push(display);
  }

  if (names.length === 0) return "(unknown)";
  if (names.length <= 3) return names.join(", ");
  return `${names.slice(0, 3).join(", ")} +${names.length - 3}`;
}

function ThreadItem({
  thread,
  isSelected,
  onSelect,
  isChecked = false,
  onCheckChange,
  selectionMode = false,
}: ThreadItemProps) {
  const selectedFolder = useUIStore((s) => s.selectedFolder);
  const selectedMailbox = useUIStore((s) => s.selectedMailbox);

  const { latest, count, has_unread } = thread;
  const rawSubject = latest.subject || "(no subject)";
  const visualSubject = stripSubjectPrefix(rawSubject) || rawSubject;
  const isMulti = count > 1;

  const senderLine = isMulti
    ? buildParticipantSummary(thread, selectedMailbox)
    : latest.from_name || extractDisplayName(latest.from_address);

  // Aggregate flags across the whole thread so chips reflect the conversation.
  const hasAttachments = thread.emails.some((e) => e.has_attachments);
  const isSigned = thread.emails.some((e) => e.is_signed);
  const isEncrypted = thread.emails.some((e) => e.is_encrypted);

  return (
    <div
      className={cn(
        "group flex w-full items-start gap-3 border-b p-3 text-left transition-colors",
        isSelected ? "bg-accent" : "hover:bg-muted/50",
        has_unread && "bg-primary/[0.03]"
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
            onChange={(e) => onCheckChange?.(latest.uid, e.target.checked)}
            className="h-4 w-4 rounded border-input accent-primary cursor-pointer"
          />
        </label>
      )}
      <button
        type="button"
        onClick={() => onSelect(thread)}
        className="flex flex-1 items-start gap-3 text-left min-w-0"
        aria-current={isSelected ? "true" : undefined}
        title={rawSubject}
      >
        <Avatar
          name={latest.from_name || extractDisplayName(latest.from_address)}
          size="sm"
        />
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between gap-2">
            <span
              className={cn(
                "text-sm truncate",
                has_unread ? "font-semibold" : "font-normal"
              )}
            >
              {senderLine}
            </span>
            <span className="text-xs text-muted-foreground whitespace-nowrap shrink-0">
              {formatEmailDate(latest.date)}
            </span>
          </div>
          <div className="flex items-center gap-1.5">
            <span
              className={cn(
                "text-sm truncate",
                has_unread
                  ? "font-medium text-foreground"
                  : "text-foreground/80"
              )}
            >
              {visualSubject}
            </span>
            {isMulti && (
              <span
                className="inline-flex items-center rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground shrink-0"
                aria-label={`${count} messages in thread`}
              >
                {count}
              </span>
            )}
            {isSigned && (
              <span title="Digitally signed">
                <Shield className="h-3 w-3 text-muted-foreground shrink-0" />
              </span>
            )}
            {isEncrypted && (
              <span title="Encrypted">
                <Lock className="h-3 w-3 text-muted-foreground shrink-0" />
              </span>
            )}
            {hasAttachments && (
              <Paperclip className="h-3 w-3 text-muted-foreground shrink-0" />
            )}
            {selectedFolder === "Junk" && (
              <span
                title="Spam"
                className="inline-flex items-center gap-0.5 rounded bg-orange-500/10 px-1 py-0.5 text-[10px] font-medium text-orange-600 dark:text-orange-400 shrink-0"
              >
                <ShieldAlert className="h-2.5 w-2.5" />
                Spam
              </span>
            )}
          </div>
          <p className="text-xs text-muted-foreground truncate mt-0.5">
            {truncate(latest.preview, 100)}
          </p>
        </div>
      </button>
    </div>
  );
}

export { ThreadItem };
