import { useState } from "react";
import { toast } from "sonner";
import { Plus, Trash2, Globe } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  useWebhooks,
  useCreateWebhook,
  useDeleteWebhook,
} from "@/hooks/use-sandbox";
import { useSandboxStore } from "@/stores/sandbox-store";

function WebhookConfig() {
  const { selectedProviderId } = useSandboxStore();
  const { data: webhooks } = useWebhooks(selectedProviderId);
  const createWebhook = useCreateWebhook();
  const deleteWebhook = useDeleteWebhook();

  const [showForm, setShowForm] = useState(false);
  const [url, setUrl] = useState("");
  const [secret, setSecret] = useState("");

  if (!selectedProviderId) {
    return (
      <p className="text-xs text-muted-foreground py-3">
        Select a provider to manage webhooks.
      </p>
    );
  }

  const handleCreate = (e: React.FormEvent) => {
    e.preventDefault();

    if (!url.trim()) {
      toast.error("URL is required");
      return;
    }

    createWebhook.mutate(
      {
        providerId: selectedProviderId,
        data: {
          url: url.trim(),
          secret: secret.trim() || undefined,
        },
      },
      {
        onSuccess: () => {
          toast.success("Webhook endpoint created");
          setUrl("");
          setSecret("");
          setShowForm(false);
        },
        onError: (error) => {
          toast.error("Failed to create webhook", {
            description: error.message,
          });
        },
      }
    );
  };

  const handleDelete = (id: string) => {
    deleteWebhook.mutate(id, {
      onSuccess: () => {
        toast.success("Webhook endpoint deleted");
      },
      onError: (error) => {
        toast.error("Failed to delete webhook", {
          description: error.message,
        });
      },
    });
  };

  return (
    <div className="space-y-2 py-1">
      {/* Existing endpoints */}
      {webhooks && webhooks.length > 0 ? (
        <div className="space-y-1.5">
          {webhooks.map((webhook) => (
            <div
              key={webhook.id}
              className="flex items-center gap-2 rounded border px-2.5 py-1.5 text-xs"
            >
              <Globe className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
              <span className="font-mono truncate flex-1">{webhook.url}</span>
              <Badge
                variant={webhook.is_active ? "default" : "outline"}
                className="text-[10px] px-1.5 py-0 shrink-0"
              >
                {webhook.is_active ? "Active" : "Inactive"}
              </Badge>
              {webhook.event_types.length > 0 && (
                <Badge variant="secondary" className="text-[10px] px-1.5 py-0 shrink-0">
                  {webhook.event_types.length} events
                </Badge>
              )}
              <Button
                variant="ghost"
                size="icon"
                className="h-6 w-6 shrink-0"
                onClick={() => handleDelete(webhook.id)}
                disabled={deleteWebhook.isPending}
              >
                <Trash2 className="h-3 w-3 text-destructive" />
              </Button>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">
          No webhook endpoints configured.
        </p>
      )}

      {/* Add form */}
      {showForm ? (
        <form onSubmit={handleCreate} className="space-y-2 rounded border p-2.5">
          <div className="space-y-1">
            <Label htmlFor="wh-url" className="text-xs">
              URL
            </Label>
            <Input
              id="wh-url"
              placeholder="https://example.com/webhook"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              className="h-8 text-xs"
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="wh-secret" className="text-xs">
              Secret (optional)
            </Label>
            <Input
              id="wh-secret"
              placeholder="webhook-secret"
              value={secret}
              onChange={(e) => setSecret(e.target.value)}
              className="h-8 text-xs"
            />
          </div>
          <div className="flex gap-1.5 justify-end">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => setShowForm(false)}
            >
              Cancel
            </Button>
            <Button type="submit" size="sm" disabled={createWebhook.isPending}>
              {createWebhook.isPending ? "Adding..." : "Add"}
            </Button>
          </div>
        </form>
      ) : (
        <Button
          variant="outline"
          size="sm"
          className="w-full gap-1.5 text-xs"
          onClick={() => setShowForm(true)}
        >
          <Plus className="h-3 w-3" />
          Add Webhook Endpoint
        </Button>
      )}
    </div>
  );
}

export { WebhookConfig };
