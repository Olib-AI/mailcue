import { useState } from "react";
import { Plus, Trash2, Settings2 } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useProviders, useDeleteProvider } from "@/hooks/use-sandbox";
import { useSandboxStore } from "@/stores/sandbox-store";
import { ProviderIcon } from "./provider-icon";
import { ProviderConfigDialog } from "./provider-config-dialog";
import type { SandboxProvider } from "@/types/sandbox";

function ProviderList() {
  const { data: providers, isLoading } = useProviders();
  const { selectedProviderId, setSelectedProviderId } = useSandboxStore();
  const [configOpen, setConfigOpen] = useState(false);
  const [editProvider, setEditProvider] = useState<SandboxProvider | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const deleteProvider = useDeleteProvider();

  const handleDelete = (e: React.MouseEvent, provider: SandboxProvider) => {
    e.stopPropagation();
    if (confirmDeleteId === provider.id) {
      deleteProvider.mutate(provider.id, {
        onSuccess: () => {
          toast.success(`Deleted ${provider.name}`);
          if (selectedProviderId === provider.id) {
            setSelectedProviderId(null);
          }
          setConfirmDeleteId(null);
        },
        onError: (error) => {
          toast.error("Failed to delete provider", { description: error.message });
          setConfirmDeleteId(null);
        },
      });
    } else {
      setConfirmDeleteId(provider.id);
    }
  };

  const handleEdit = (e: React.MouseEvent, provider: SandboxProvider) => {
    e.stopPropagation();
    setEditProvider(provider);
    setConfigOpen(true);
  };

  return (
    <>
      <div className="flex items-center justify-between border-b px-3 h-12 shrink-0">
        <h2 className="text-sm font-semibold">Providers</h2>
      </div>

      <ScrollArea className="flex-1">
        <div className="p-2 space-y-1">
          {isLoading ? (
            <>
              <Skeleton className="h-16 w-full rounded-md" />
              <Skeleton className="h-16 w-full rounded-md" />
              <Skeleton className="h-16 w-full rounded-md" />
            </>
          ) : !providers || providers.length === 0 ? (
            <div className="px-3 py-8 text-center text-sm text-muted-foreground">
              No providers configured. Add one to get started.
            </div>
          ) : (
            providers.map((provider) => (
              <div
                key={provider.id}
                className={cn(
                  "group relative flex w-full items-start gap-3 rounded-md p-3 text-left text-sm transition-colors cursor-pointer",
                  selectedProviderId === provider.id
                    ? "bg-accent text-accent-foreground"
                    : "hover:bg-muted/50"
                )}
                onClick={() => setSelectedProviderId(provider.id)}
                onMouseLeave={() => {
                  if (confirmDeleteId === provider.id) setConfirmDeleteId(null);
                }}
              >
                <ProviderIcon
                  type={provider.provider_type}
                  className="mt-0.5 shrink-0"
                />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-medium truncate">
                      {provider.name}
                    </span>
                  </div>
                  <div className="flex items-center gap-1.5 mt-1">
                    <Badge variant="secondary" className="text-[10px] px-1.5 py-0">
                      {provider.provider_type}
                    </Badge>
                    <Badge
                      variant={provider.is_active ? "default" : "outline"}
                      className="text-[10px] px-1.5 py-0"
                    >
                      {provider.is_active ? "Active" : "Inactive"}
                    </Badge>
                  </div>
                </div>

                {/* Action buttons - visible on hover */}
                <div className="absolute top-2 right-2 flex gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-6 w-6"
                    onClick={(e) => handleEdit(e, provider)}
                  >
                    <Settings2 className="h-3 w-3" />
                  </Button>
                  <Button
                    variant={confirmDeleteId === provider.id ? "destructive" : "ghost"}
                    size="icon"
                    className="h-6 w-6"
                    onClick={(e) => handleDelete(e, provider)}
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
            setEditProvider(null);
            setConfigOpen(true);
          }}
        >
          <Plus className="h-3.5 w-3.5" />
          Add Provider
        </Button>
      </div>

      <ProviderConfigDialog
        open={configOpen}
        onOpenChange={setConfigOpen}
        provider={editProvider}
      />
    </>
  );
}

export { ProviderList };
