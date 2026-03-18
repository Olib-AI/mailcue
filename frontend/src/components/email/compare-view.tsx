import { useState, useMemo } from "react";
import { useQueries } from "@tanstack/react-query";
import { X, Loader2, AlertCircle, ChevronDown, ChevronUp } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { diffLines, diffWords, type DiffLine } from "@/lib/diff";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { useCompareStore, type CompareEmailRef } from "@/stores/compare-store";
import { emailKeys } from "@/hooks/use-emails";
import type { EmailDetail } from "@/types/api";

// ---------------------------------------------------------------------------
// Diff rendering helpers
// ---------------------------------------------------------------------------

function DiffLineView({ line }: { line: DiffLine }) {
  return (
    <div
      className={cn(
        "px-3 py-0.5 font-mono text-xs leading-5 whitespace-pre-wrap",
        line.op === "add" && "bg-green-500/15 text-green-700 dark:text-green-400",
        line.op === "remove" && "bg-red-500/15 text-red-700 dark:text-red-400"
      )}
    >
      <span className="inline-block w-4 select-none text-muted-foreground mr-2">
        {line.op === "add" ? "+" : line.op === "remove" ? "-" : " "}
      </span>
      {line.text}
    </div>
  );
}

function InlineWordDiff({ oldText, newText }: { oldText: string; newText: string }) {
  const words = useMemo(() => diffWords(oldText, newText), [oldText, newText]);

  return (
    <span className="text-xs font-mono">
      {words.map((w, i) => (
        <span
          key={i}
          className={cn(
            w.op === "add" && "bg-green-500/20 text-green-700 dark:text-green-400",
            w.op === "remove" && "bg-red-500/20 text-red-700 dark:text-red-400 line-through"
          )}
        >
          {w.text}
        </span>
      ))}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Header diff section
// ---------------------------------------------------------------------------


// ---------------------------------------------------------------------------
// All headers compare (raw_headers with important ones pinned at top)
// ---------------------------------------------------------------------------

const PINNED_HEADERS = [
  "Subject",
  "From",
  "To",
  "Cc",
  "Date",
  "Message-ID",
  "Reply-To",
  "In-Reply-To",
  "References",
  "MIME-Version",
  "Content-Type",
  "Content-Transfer-Encoding",
  "Return-Path",
  "Received",
  "DKIM-Signature",
  "Authentication-Results",
  "ARC-Authentication-Results",
  "ARC-Message-Signature",
  "ARC-Seal",
  "X-Spam-Status",
  "X-Spam-Score",
  "X-Mailer",
];

function AllHeadersCompare({ emails }: { emails: EmailDetail[] }) {
  const [showIdentical, setShowIdentical] = useState(false);

  const { pinned, rest, differingCount, totalCount } = useMemo(() => {
    const keySet = new Set<string>();
    for (const email of emails) {
      for (const key of Object.keys(email.raw_headers)) {
        keySet.add(key);
      }
    }
    const allKeys = Array.from(keySet);

    const pinnedLower = PINNED_HEADERS.map((h) => h.toLowerCase());
    const pinnedKeys: string[] = [];
    const restKeys: string[] = [];

    for (const key of allKeys) {
      const idx = pinnedLower.indexOf(key.toLowerCase());
      if (idx !== -1) {
        pinnedKeys.push(key);
      } else {
        restKeys.push(key);
      }
    }

    pinnedKeys.sort(
      (a, b) =>
        pinnedLower.indexOf(a.toLowerCase()) - pinnedLower.indexOf(b.toLowerCase())
    );
    restKeys.sort((a, b) => a.localeCompare(b));

    let diffCount = 0;
    for (const key of allKeys) {
      const values = emails.map((e) => e.raw_headers[key] ?? "");
      if (!values.every((v) => v === values[0])) diffCount++;
    }

    return { pinned: pinnedKeys, rest: restKeys, differingCount: diffCount, totalCount: allKeys.length };
  }, [emails]);

  const renderRow = (key: string) => {
    const values = emails.map((e) => e.raw_headers[key] ?? "");
    const allSame = values.every((v) => v === values[0]);

    if (!showIdentical && allSame) return null;

    return (
      <div
        key={key}
        className={cn("rounded px-2 py-1.5", !allSame && "bg-yellow-500/5")}
      >
        <div className="flex items-center gap-2 mb-0.5">
          <span className="text-xs font-semibold text-muted-foreground">{key}</span>
          {!allSame && (
            <Badge variant="outline" className="text-[10px] px-1 py-0 h-4 text-yellow-700 dark:text-yellow-400 border-yellow-500/30">
              differs
            </Badge>
          )}
        </div>
        {values.length === 2 && !allSame ? (
          <InlineWordDiff oldText={values[0] ?? ""} newText={values[1] ?? ""} />
        ) : (
          <div
            className="grid gap-1"
            style={{ gridTemplateColumns: `repeat(${values.length}, 1fr)` }}
          >
            {values.map((val, i) => (
              <span
                key={i}
                className={cn(
                  "text-xs font-mono break-all",
                  !allSame && "bg-yellow-500/10 px-1 rounded"
                )}
              >
                {val || "-"}
              </span>
            ))}
          </div>
        )}
      </div>
    );
  };

  const hasVisibleRest = rest.some((k) => {
    const values = emails.map((e) => e.raw_headers[k] ?? "");
    return showIdentical || !values.every((v) => v === values[0]);
  });

  const hasVisiblePinned = pinned.some((k) => {
    const values = emails.map((e) => e.raw_headers[k] ?? "");
    return showIdentical || !values.every((v) => v === values[0]);
  });

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-xs text-muted-foreground">
          {differingCount} of {totalCount} header{totalCount !== 1 ? "s" : ""} differ
        </span>
        <Button
          variant="ghost"
          size="sm"
          className="h-6 text-xs"
          onClick={() => setShowIdentical(!showIdentical)}
        >
          {showIdentical ? (
            <>
              <ChevronUp className="h-3 w-3 mr-1" />
              Hide identical
            </>
          ) : (
            <>
              <ChevronDown className="h-3 w-3 mr-1" />
              Show all ({totalCount})
            </>
          )}
        </Button>
      </div>
      <div className="rounded-lg border overflow-hidden">
        <ScrollArea className="max-h-[500px]">
          <div className="p-3 space-y-0.5">
            {pinned.map(renderRow)}
            {hasVisiblePinned && hasVisibleRest && (
              <Separator className="my-2" />
            )}
            {rest.map(renderRow)}
            {differingCount === 0 && !showIdentical && (
              <div className="text-center py-4 text-sm text-muted-foreground">
                All headers are identical.
              </div>
            )}
          </div>
        </ScrollArea>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Body diff panel
// ---------------------------------------------------------------------------

interface BodyDiffPanelProps {
  emails: EmailDetail[];
  leftIndex: number;
  rightIndex: number;
}

function BodyDiffPanel({ emails, leftIndex, rightIndex }: BodyDiffPanelProps) {
  const left = emails[leftIndex];
  const right = emails[rightIndex];

  const leftBody = left?.text_body ?? left?.html_body ?? "";
  const rightBody = right?.text_body ?? right?.html_body ?? "";

  // Strip HTML tags for a text-based comparison when using html_body
  const stripHtml = (html: string) =>
    html.replace(/<[^>]*>/g, "").replace(/&nbsp;/g, " ").replace(/\s+/g, " ").trim();

  const leftText = left?.text_body ? leftBody : stripHtml(leftBody);
  const rightText = right?.text_body ? rightBody : stripHtml(rightBody);

  const diff = useMemo(() => diffLines(leftText, rightText), [leftText, rightText]);

  const hasChanges = diff.some((d) => d.op !== "equal");

  if (!hasChanges) {
    return (
      <div className="flex items-center justify-center py-8 text-sm text-muted-foreground">
        Email bodies are identical.
      </div>
    );
  }

  return (
    <div className="rounded-lg border overflow-hidden">
      <div className="bg-muted px-3 py-1.5 flex items-center justify-between text-xs text-muted-foreground border-b">
        <span>
          <span className="text-red-600 dark:text-red-400 font-medium">
            {diff.filter((d) => d.op === "remove").length} removed
          </span>
          {" / "}
          <span className="text-green-600 dark:text-green-400 font-medium">
            {diff.filter((d) => d.op === "add").length} added
          </span>
        </span>
      </div>
      <ScrollArea className="max-h-[500px]">
        {diff.map((line, i) => (
          <DiffLineView key={i} line={line} />
        ))}
      </ScrollArea>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Side-by-side panel (non-diff, shows raw content)
// ---------------------------------------------------------------------------

interface SideBySidePanelProps {
  emails: EmailDetail[];
}

function SideBySidePanel({ emails }: SideBySidePanelProps) {
  return (
    <div className="grid gap-4" style={{ gridTemplateColumns: `repeat(${emails.length}, 1fr)` }}>
      {emails.map((email) => (
        <div key={email.uid} className="rounded-lg border overflow-hidden">
          <div className="bg-muted px-3 py-1.5 text-xs font-medium truncate border-b">
            {email.subject || "(no subject)"}
          </div>
          <ScrollArea className="max-h-[500px]">
            <pre className="whitespace-pre-wrap font-mono text-xs p-3 leading-5">
              {email.text_body ?? "(no text body)"}
            </pre>
          </ScrollArea>
        </div>
      ))}
    </div>
  );
}


// ---------------------------------------------------------------------------
// Pair selector (when > 2 emails are selected)
// ---------------------------------------------------------------------------

interface PairSelectorProps {
  refs: CompareEmailRef[];
  leftIndex: number;
  rightIndex: number;
  onLeftChange: (index: number) => void;
  onRightChange: (index: number) => void;
}

function PairSelector({ refs, leftIndex, rightIndex, onLeftChange, onRightChange }: PairSelectorProps) {
  if (refs.length <= 2) return null;

  return (
    <div className="flex items-center gap-4 text-xs">
      <label className="flex items-center gap-1.5">
        <span className="text-muted-foreground">Left:</span>
        <select
          value={leftIndex}
          onChange={(e) => onLeftChange(Number(e.target.value))}
          className="rounded border bg-background px-2 py-1 text-xs"
        >
          {refs.map((ref, i) => (
            <option key={`${ref.mailbox}:${ref.uid}`} value={i}>
              {ref.subject || "(no subject)"} — {ref.from_address}
            </option>
          ))}
        </select>
      </label>
      <label className="flex items-center gap-1.5">
        <span className="text-muted-foreground">Right:</span>
        <select
          value={rightIndex}
          onChange={(e) => onRightChange(Number(e.target.value))}
          className="rounded border bg-background px-2 py-1 text-xs"
        >
          {refs.map((ref, i) => (
            <option key={`${ref.mailbox}:${ref.uid}`} value={i}>
              {ref.subject || "(no subject)"} — {ref.from_address}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main CompareView dialog
// ---------------------------------------------------------------------------

function CompareView() {
  const { emails: emailRefs, compareViewOpen, setCompareViewOpen, removeEmail } =
    useCompareStore();

  const refs = useMemo(() => Array.from(emailRefs.values()), [emailRefs]);

  const [leftIndex, setLeftIndex] = useState(0);
  const [rightIndex, setRightIndex] = useState(1);

  // Fetch full details for all selected emails
  const queries = useQueries({
    queries: refs.map((ref) => ({
      queryKey: emailKeys.detail(ref.mailbox, ref.uid),
      queryFn: () => {
        const params = new URLSearchParams({ folder: ref.folder });
        return api.get<EmailDetail>(
          `/mailboxes/${encodeURIComponent(ref.mailbox)}/emails/${encodeURIComponent(ref.uid)}?${params.toString()}`
        );
      },
      staleTime: 120_000,
      enabled: compareViewOpen,
    })),
  });

  const isLoading = queries.some((q) => q.isLoading);
  const hasError = queries.some((q) => q.isError);
  const loadedEmails = queries
    .map((q) => q.data)
    .filter((d): d is EmailDetail => d !== undefined);

  const allLoaded = loadedEmails.length === refs.length;

  // Clamp indices when emails are removed
  const safeLeft = Math.min(leftIndex, Math.max(0, refs.length - 1));
  const safeRight = Math.min(rightIndex, Math.max(0, refs.length - 1));

  return (
    <Dialog open={compareViewOpen} onOpenChange={setCompareViewOpen}>
      <DialogContent className="max-w-5xl w-[95vw] max-h-[90vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            Compare Emails
            <Badge variant="secondary" className="text-xs">
              {refs.length} selected
            </Badge>
          </DialogTitle>
        </DialogHeader>

        {/* Selected email chips */}
        <div className="flex flex-wrap gap-1.5">
          {refs.map((ref, i) => (
            <span
              key={`${ref.mailbox}:${ref.uid}`}
              className="inline-flex items-center gap-1.5 rounded-md bg-muted px-2.5 py-1 text-xs"
            >
              <span className="font-medium text-muted-foreground">#{i + 1}</span>
              <span className="truncate max-w-[200px]">
                {ref.subject || "(no subject)"}
              </span>
              <button
                type="button"
                onClick={() => removeEmail(ref.mailbox, ref.uid)}
                className="shrink-0 rounded hover:bg-background p-0.5"
                aria-label="Remove from compare"
              >
                <X className="h-3 w-3" />
              </button>
            </span>
          ))}
        </div>

        <Separator />

        {/* Content */}
        <ScrollArea className="flex-1 min-h-0">
          {isLoading && (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
              <span className="ml-2 text-sm text-muted-foreground">
                Loading email details...
              </span>
            </div>
          )}

          {hasError && !isLoading && (
            <div className="flex items-center justify-center py-12">
              <AlertCircle className="h-6 w-6 text-destructive" />
              <span className="ml-2 text-sm text-destructive">
                Failed to load one or more emails.
              </span>
            </div>
          )}

          {!isLoading && allLoaded && loadedEmails.length >= 2 && (
            <div className="space-y-4 p-1">
              {/* Pair selector for > 2 emails */}
              <PairSelector
                refs={refs}
                leftIndex={safeLeft}
                rightIndex={safeRight}
                onLeftChange={setLeftIndex}
                onRightChange={setRightIndex}
              />

              <Tabs defaultValue="headers">
                <TabsList>
                  <TabsTrigger value="headers">Headers</TabsTrigger>
                  <TabsTrigger value="body-diff">Body Diff</TabsTrigger>
                  <TabsTrigger value="side-by-side">Side by Side</TabsTrigger>
                </TabsList>

                <TabsContent value="headers">
                  <AllHeadersCompare emails={loadedEmails} />
                </TabsContent>

                <TabsContent value="body-diff">
                  <BodyDiffPanel
                    emails={loadedEmails}
                    leftIndex={safeLeft}
                    rightIndex={safeRight}
                  />
                </TabsContent>

                <TabsContent value="side-by-side">
                  <SideBySidePanel emails={loadedEmails} />
                </TabsContent>

              </Tabs>
            </div>
          )}

          {!isLoading && allLoaded && loadedEmails.length < 2 && (
            <div className="flex items-center justify-center py-12 text-sm text-muted-foreground">
              Select at least 2 emails to compare.
            </div>
          )}
        </ScrollArea>
      </DialogContent>
    </Dialog>
  );
}

export { CompareView };
