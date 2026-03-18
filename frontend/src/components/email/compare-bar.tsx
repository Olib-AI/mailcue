import { GitCompareArrows, X, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useCompareStore } from "@/stores/compare-store";
import { truncate } from "@/lib/utils";

function CompareBar() {
  const { emails, removeEmail, clearAll, setCompareViewOpen } =
    useCompareStore();

  const count = emails.size;

  if (count === 0) return null;

  const emailList = Array.from(emails.values());

  return (
    <div className="fixed bottom-4 left-1/2 -translate-x-1/2 z-40 flex items-center gap-3 rounded-lg border bg-background/95 backdrop-blur-sm shadow-lg px-4 py-2.5 max-w-[600px]">
      <div className="flex items-center gap-2 shrink-0">
        <GitCompareArrows className="h-4 w-4 text-primary" />
        <Badge variant="default" className="text-xs">
          {count}
        </Badge>
      </div>

      <div className="flex items-center gap-1.5 min-w-0 overflow-hidden">
        {emailList.map((ref) => (
          <span
            key={`${ref.mailbox}:${ref.uid}`}
            className="inline-flex items-center gap-1 rounded-md bg-muted px-2 py-0.5 text-xs max-w-[140px]"
          >
            <span className="truncate">
              {truncate(ref.subject || "(no subject)", 20)}
            </span>
            <button
              type="button"
              onClick={() => removeEmail(ref.mailbox, ref.uid)}
              className="shrink-0 rounded hover:bg-background p-0.5"
              aria-label={`Remove "${ref.subject}" from compare`}
            >
              <X className="h-3 w-3" />
            </button>
          </span>
        ))}
      </div>

      <div className="flex items-center gap-1.5 shrink-0 ml-auto">
        <Button
          variant="default"
          size="sm"
          disabled={count < 2}
          onClick={() => setCompareViewOpen(true)}
          className="text-xs"
        >
          <GitCompareArrows className="h-3.5 w-3.5 mr-1" />
          Compare
        </Button>
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7 text-muted-foreground"
          onClick={clearAll}
          aria-label="Clear all compare selections"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </Button>
      </div>
    </div>
  );
}

export { CompareBar };
