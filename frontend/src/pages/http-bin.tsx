import { useState } from "react";
import {
  Globe,
  Plus,
  Copy,
  Check,
  Trash2,
  XCircle,
  Inbox,
  Settings2,
  ChevronDown,
  ChevronRight,
} from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Skeleton } from "@/components/ui/skeleton";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  useBins,
  useBin,
  useCreateBin,
  useUpdateBin,
  useDeleteBin,
  useBinRequests,
  useClearBinRequests,
} from "@/hooks/use-httpbin";
import { useHttpBinStore } from "@/stores/httpbin-store";
import type { HttpBinBin, HttpBinCapturedRequest } from "@/types/httpbin";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const METHOD_COLORS: Record<string, string> = {
  GET: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400",
  POST: "bg-blue-500/15 text-blue-700 dark:text-blue-400",
  PUT: "bg-amber-500/15 text-amber-700 dark:text-amber-400",
  PATCH: "bg-orange-500/15 text-orange-700 dark:text-orange-400",
  DELETE: "bg-red-500/15 text-red-700 dark:text-red-400",
  HEAD: "bg-purple-500/15 text-purple-700 dark:text-purple-400",
  OPTIONS: "bg-gray-500/15 text-gray-700 dark:text-gray-400",
};

function formatTime(dateString: string): string {
  return new Date(dateString).toLocaleTimeString("en-US", {
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
    hour12: true,
  });
}

function CopyButton({ text, className }: { text: string; className?: string }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = () => {
    void navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };
  return (
    <Button
      variant="ghost"
      size="icon"
      className={cn("h-7 w-7", className)}
      onClick={(e) => {
        e.stopPropagation();
        handleCopy();
      }}
    >
      {copied ? (
        <Check className="h-3.5 w-3.5 text-green-500" />
      ) : (
        <Copy className="h-3.5 w-3.5" />
      )}
    </Button>
  );
}

function getBinUrl(binId: string): string {
  return `${window.location.origin}/httpbin/${binId}`;
}

// ---------------------------------------------------------------------------
// CreateBinDialog
// ---------------------------------------------------------------------------

function CreateBinDialog({
  open,
  onOpenChange,
  editBin,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  editBin: HttpBinBin | null;
}) {
  const [name, setName] = useState(editBin?.name ?? "");
  const [statusCode, setStatusCode] = useState(
    editBin?.response_status_code ?? 200
  );
  const [body, setBody] = useState(editBin?.response_body ?? "");
  const [contentType, setContentType] = useState(
    editBin?.response_content_type ?? "application/json"
  );

  const createBin = useCreateBin();
  const updateBin = useUpdateBin();
  const isEdit = editBin !== null;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) {
      toast.error("Name is required");
      return;
    }

    const data = {
      name: name.trim(),
      response_status_code: statusCode,
      response_body: body,
      response_content_type: contentType,
    };

    if (isEdit) {
      updateBin.mutate(
        { id: editBin.id, data },
        {
          onSuccess: () => {
            toast.success("Bin updated");
            onOpenChange(false);
          },
          onError: (err) =>
            toast.error("Failed to update bin", { description: err.message }),
        }
      );
    } else {
      createBin.mutate(data, {
        onSuccess: () => {
          toast.success("Bin created");
          setName("");
          setStatusCode(200);
          setBody("");
          setContentType("application/json");
          onOpenChange(false);
        },
        onError: (err) =>
          toast.error("Failed to create bin", { description: err.message }),
      });
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{isEdit ? "Edit Bin" : "Create Bin"}</DialogTitle>
          <DialogDescription>
            {isEdit
              ? "Update the bin configuration."
              : "Create a new HTTP bin to capture incoming requests."}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="bin-name">Name</Label>
            <Input
              id="bin-name"
              placeholder="e.g. Webhook Test"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="bin-status">Response Status</Label>
              <Input
                id="bin-status"
                type="number"
                min={100}
                max={599}
                value={statusCode}
                onChange={(e) => setStatusCode(Number(e.target.value))}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="bin-ct">Content-Type</Label>
              <Input
                id="bin-ct"
                value={contentType}
                onChange={(e) => setContentType(e.target.value)}
              />
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="bin-body">Response Body</Label>
            <Textarea
              id="bin-body"
              rows={4}
              placeholder='{"ok": true}'
              value={body}
              onChange={(e) => setBody(e.target.value)}
              className="font-mono text-xs"
            />
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={createBin.isPending || updateBin.isPending}
            >
              {isEdit ? "Save" : "Create"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// BinList (left panel)
// ---------------------------------------------------------------------------

function BinList() {
  const { data: bins, isLoading } = useBins();
  const { selectedBinId, setSelectedBinId } = useHttpBinStore();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editBin, setEditBin] = useState<HttpBinBin | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const deleteBin = useDeleteBin();

  const handleDelete = (e: React.MouseEvent, bin: HttpBinBin) => {
    e.stopPropagation();
    if (confirmDeleteId === bin.id) {
      deleteBin.mutate(bin.id, {
        onSuccess: () => {
          toast.success(`Deleted ${bin.name}`);
          if (selectedBinId === bin.id) setSelectedBinId(null);
          setConfirmDeleteId(null);
        },
        onError: (err) => {
          toast.error("Failed to delete", { description: err.message });
          setConfirmDeleteId(null);
        },
      });
    } else {
      setConfirmDeleteId(bin.id);
    }
  };

  return (
    <>
      <div className="flex items-center justify-between border-b px-3 h-12 shrink-0">
        <h2 className="text-sm font-semibold">HTTP Bins</h2>
      </div>

      <ScrollArea className="flex-1">
        <div className="p-2 space-y-1">
          {isLoading ? (
            <>
              <Skeleton className="h-16 w-full rounded-md" />
              <Skeleton className="h-16 w-full rounded-md" />
            </>
          ) : !bins || bins.length === 0 ? (
            <div className="px-3 py-8 text-center text-sm text-muted-foreground">
              No bins yet. Create one to get started.
            </div>
          ) : (
            bins.map((bin) => (
              <div
                key={bin.id}
                className={cn(
                  "group relative flex w-full items-start gap-3 rounded-md p-3 text-left text-sm transition-colors cursor-pointer",
                  selectedBinId === bin.id
                    ? "bg-accent text-accent-foreground"
                    : "hover:bg-muted/50"
                )}
                onClick={() => setSelectedBinId(bin.id)}
                onMouseLeave={() => {
                  if (confirmDeleteId === bin.id) setConfirmDeleteId(null);
                }}
              >
                <Globe className="h-4 w-4 mt-0.5 shrink-0 text-muted-foreground" />
                <div className="flex-1 min-w-0">
                  <span className="font-medium truncate block">{bin.name}</span>
                  <div className="flex items-center gap-1.5 mt-1">
                    <Badge variant="secondary" className="text-[10px] px-1.5 py-0">
                      {bin.request_count} req
                    </Badge>
                    <Badge variant="outline" className="text-[10px] px-1.5 py-0">
                      {bin.response_status_code}
                    </Badge>
                  </div>
                </div>

                <div className="absolute top-2 right-2 flex gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-6 w-6"
                    onClick={(e) => {
                      e.stopPropagation();
                      setEditBin(bin);
                      setDialogOpen(true);
                    }}
                  >
                    <Settings2 className="h-3 w-3" />
                  </Button>
                  <CopyButton text={getBinUrl(bin.id)} className="h-6 w-6" />
                  <Button
                    variant={confirmDeleteId === bin.id ? "destructive" : "ghost"}
                    size="icon"
                    className="h-6 w-6"
                    onClick={(e) => handleDelete(e, bin)}
                  >
                    <Trash2 className="h-3 w-3" />
                  </Button>
                </div>
              </div>
            ))
          )}
        </div>
      </ScrollArea>

      <div className="border-t p-2 shrink-0">
        <Button
          variant="outline"
          size="sm"
          className="w-full gap-2"
          onClick={() => {
            setEditBin(null);
            setDialogOpen(true);
          }}
        >
          <Plus className="h-3.5 w-3.5" />
          Create Bin
        </Button>
      </div>

      <CreateBinDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        editBin={editBin}
      />
    </>
  );
}

// ---------------------------------------------------------------------------
// RequestRow (expandable)
// ---------------------------------------------------------------------------

function RequestRow({ req }: { req: HttpBinCapturedRequest }) {
  const [expanded, setExpanded] = useState(false);

  const methodColor =
    METHOD_COLORS[req.method] ??
    "bg-gray-500/15 text-gray-700 dark:text-gray-400";

  let parsedBody: unknown = null;
  if (req.body) {
    try {
      parsedBody = JSON.parse(req.body) as unknown;
    } catch {
      parsedBody = null;
    }
  }

  const headerEntries = Object.entries(req.headers);
  const queryEntries = Object.entries(req.query_params);

  return (
    <div className="rounded-md border text-sm">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center gap-2.5 px-3 py-2 hover:bg-muted/50 transition-colors cursor-pointer"
      >
        {expanded ? (
          <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        )}
        <Badge
          className={cn(
            "text-[11px] px-2 py-0 font-mono font-semibold shrink-0",
            methodColor
          )}
          variant="secondary"
        >
          {req.method}
        </Badge>
        <span className="font-mono text-xs truncate">{req.path}</span>
        <span className="text-xs text-muted-foreground ml-auto shrink-0">
          {req.remote_addr}
        </span>
        <span className="text-xs text-muted-foreground shrink-0">
          {formatTime(req.created_at)}
        </span>
      </button>

      {expanded && (
        <div className="border-t px-3 py-3 space-y-3">
          {/* Headers */}
          {headerEntries.length > 0 && (
            <div>
              <h4 className="text-xs font-semibold text-muted-foreground mb-1.5">
                Headers
              </h4>
              <div className="rounded border overflow-hidden">
                <table className="w-full text-xs">
                  <tbody>
                    {headerEntries.map(([key, value]) => (
                      <tr key={key} className="border-b last:border-b-0">
                        <td className="px-2 py-1 font-mono font-medium bg-muted/30 w-1/3 align-top">
                          {key}
                        </td>
                        <td className="px-2 py-1 font-mono break-all">
                          {String(value)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Query Params */}
          {queryEntries.length > 0 && (
            <div>
              <h4 className="text-xs font-semibold text-muted-foreground mb-1.5">
                Query Parameters
              </h4>
              <div className="rounded border overflow-hidden">
                <table className="w-full text-xs">
                  <tbody>
                    {queryEntries.map(([key, value]) => (
                      <tr key={key} className="border-b last:border-b-0">
                        <td className="px-2 py-1 font-mono font-medium bg-muted/30 w-1/3">
                          {key}
                        </td>
                        <td className="px-2 py-1 font-mono break-all">
                          {String(value)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Body */}
          {req.body && (
            <div>
              <div className="flex items-center justify-between mb-1.5">
                <h4 className="text-xs font-semibold text-muted-foreground">
                  Body
                </h4>
                <CopyButton text={req.body} className="h-5 w-5" />
              </div>
              <pre className="rounded border bg-muted/30 p-2 text-xs font-mono overflow-auto max-h-64 whitespace-pre-wrap break-all">
                {parsedBody
                  ? JSON.stringify(parsedBody, null, 2)
                  : req.body}
              </pre>
            </div>
          )}

          {!req.body && queryEntries.length === 0 && headerEntries.length === 0 && (
            <p className="text-xs text-muted-foreground">No data captured.</p>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// RequestPanel (right side)
// ---------------------------------------------------------------------------

function RequestPanel() {
  const { selectedBinId } = useHttpBinStore();
  const { data: bin } = useBin(selectedBinId);
  const { data: requestData, isLoading } = useBinRequests(selectedBinId);
  const clearRequests = useClearBinRequests();

  const requests = requestData?.requests ?? [];

  if (!selectedBinId) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-3 text-muted-foreground">
        <Globe className="h-12 w-12 opacity-40" />
        <p className="text-sm">Select a bin to view captured requests</p>
      </div>
    );
  }

  const binUrl = getBinUrl(selectedBinId);

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {/* Top bar */}
      <div className="flex items-center justify-between border-b px-4 h-12 shrink-0 gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-sm font-semibold truncate">
            {bin?.name ?? "Requests"}
          </span>
          <Badge variant="outline" className="text-[10px] shrink-0">
            {requestData?.total ?? 0} captured
          </Badge>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <Badge
            variant="outline"
            className="text-xs font-mono max-w-[300px] truncate"
          >
            {binUrl}
          </Badge>
          <CopyButton text={binUrl} />
          {requests.length > 0 && (
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7 hover:bg-destructive hover:text-destructive-foreground"
              onClick={() =>
                clearRequests.mutate(selectedBinId, {
                  onSuccess: () => toast.success("Requests cleared"),
                })
              }
            >
              <XCircle className="h-3.5 w-3.5" />
            </Button>
          )}
        </div>
      </div>

      {/* Response config bar */}
      {bin && (
        <div className="flex items-center gap-3 px-4 py-2 border-b bg-muted/30 text-xs text-muted-foreground shrink-0">
          <span>
            Response:{" "}
            <span className="font-mono font-medium text-foreground">
              {bin.response_status_code}
            </span>
          </span>
          <Separator orientation="vertical" className="h-3" />
          <span className="font-mono">{bin.response_content_type}</span>
          {bin.response_body && (
            <>
              <Separator orientation="vertical" className="h-3" />
              <span className="font-mono truncate max-w-[200px]">
                {bin.response_body}
              </span>
            </>
          )}
        </div>
      )}

      {/* Request list */}
      <ScrollArea className="flex-1">
        <div className="p-4 space-y-2">
          {isLoading ? (
            <>
              <Skeleton className="h-10 w-full rounded-md" />
              <Skeleton className="h-10 w-full rounded-md" />
              <Skeleton className="h-10 w-full rounded-md" />
            </>
          ) : requests.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 text-muted-foreground gap-3">
              <Inbox className="h-10 w-10 opacity-40" />
              <p className="text-sm font-medium">No requests captured yet</p>
              <p className="text-xs text-center max-w-xs">
                Send a request to your bin URL to see it here. Try:
              </p>
              <pre className="rounded border bg-muted px-3 py-2 text-xs font-mono select-all max-w-full overflow-auto">
                curl -X POST {binUrl} -H &quot;Content-Type: application/json&quot; -d
                &apos;{`{"hello":"world"}`}&apos;
              </pre>
            </div>
          ) : (
            requests.map((req) => <RequestRow key={req.id} req={req} />)
          )}
        </div>
      </ScrollArea>
    </div>
  );
}

// ---------------------------------------------------------------------------
// HttpBinPage
// ---------------------------------------------------------------------------

function HttpBinPage() {
  return (
    <div className="flex h-full">
      <div className="w-64 min-w-[220px] border-r flex flex-col overflow-hidden">
        <BinList />
      </div>
      <RequestPanel />
    </div>
  );
}

export { HttpBinPage };
