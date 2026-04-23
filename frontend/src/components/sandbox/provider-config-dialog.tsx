import { useState, useEffect } from "react";
import { toast } from "sonner";
import { Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  useCreateProvider,
  useUpdateProvider,
  useDeleteProvider,
} from "@/hooks/use-sandbox";
import { useSandboxStore } from "@/stores/sandbox-store";
import type { SandboxProvider, ProviderType } from "@/types/sandbox";

const CREDENTIAL_FIELDS: Record<ProviderType, { key: string; label: string; placeholder: string }[]> = {
  telegram: [
    { key: "bot_token", label: "Bot Token", placeholder: "123456:ABC-DEF..." },
  ],
  slack: [
    { key: "bot_token", label: "Bot Token", placeholder: "xoxb-..." },
    { key: "signing_secret", label: "Signing Secret", placeholder: "abc123..." },
  ],
  mattermost: [
    { key: "access_token", label: "Access Token", placeholder: "abc123..." },
  ],
  twilio: [
    { key: "account_sid", label: "Account SID", placeholder: "AC..." },
    { key: "auth_token", label: "Auth Token", placeholder: "abc123..." },
  ],
  whatsapp: [
    { key: "access_token", label: "Access Token", placeholder: "EAABx..." },
    { key: "phone_number_id", label: "Phone Number ID", placeholder: "106540352..." },
  ],
  discord: [
    { key: "bot_token", label: "Bot Token", placeholder: "MTI3..." },
    { key: "application_id", label: "Application ID", placeholder: "1234567890..." },
  ],
  bandwidth: [
    { key: "account_id", label: "Account ID", placeholder: "bw-acc-12345" },
    { key: "username", label: "Username", placeholder: "api-user" },
    { key: "password", label: "Password", placeholder: "api-secret" },
    { key: "application_id", label: "Messaging Application ID", placeholder: "msg-app-1" },
    { key: "voice_application_id", label: "Voice Application ID", placeholder: "voice-app-1" },
  ],
  vonage: [
    { key: "api_key", label: "API Key", placeholder: "abc123" },
    { key: "api_secret", label: "API Secret", placeholder: "def456" },
    { key: "application_id", label: "Application ID", placeholder: "app-id-1" },
    { key: "messages_token", label: "Messages Bearer Token", placeholder: "eyJ..." },
  ],
  plivo: [
    { key: "auth_id", label: "Auth ID", placeholder: "MAXXXXXXXXXXX" },
    { key: "auth_token", label: "Auth Token", placeholder: "secret-token" },
  ],
  telnyx: [
    { key: "api_key", label: "API Key", placeholder: "KEY..." },
  ],
};

const PROVIDER_LABELS: Record<ProviderType, string> = {
  telegram: "Telegram",
  slack: "Slack",
  mattermost: "Mattermost",
  twilio: "Twilio",
  whatsapp: "WhatsApp",
  discord: "Discord",
  bandwidth: "Bandwidth",
  vonage: "Vonage",
  plivo: "Plivo",
  telnyx: "Telnyx",
};

interface ProviderConfigDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  provider: SandboxProvider | null;
}

function ProviderConfigDialog({
  open,
  onOpenChange,
  provider,
}: ProviderConfigDialogProps) {
  const isEditing = provider !== null;

  const [providerType, setProviderType] = useState<ProviderType>("telegram");
  const [name, setName] = useState("");
  const [credentials, setCredentials] = useState<Record<string, string>>({});
  const [confirmDelete, setConfirmDelete] = useState(false);

  const createProvider = useCreateProvider();
  const updateProvider = useUpdateProvider();
  const deleteProvider = useDeleteProvider();
  const { setSelectedProviderId } = useSandboxStore();

  // Reset form when provider or open state changes
  useEffect(() => {
    if (open) {
      if (provider) {
        setProviderType(provider.provider_type);
        setName(provider.name);
        setCredentials({ ...provider.credentials });
      } else {
        setProviderType("telegram");
        setName("");
        setCredentials({});
      }
      setConfirmDelete(false);
    }
  }, [open, provider]);

  const credentialFields = CREDENTIAL_FIELDS[providerType] ?? [];

  const handleCredentialChange = (key: string, value: string) => {
    setCredentials((prev) => ({ ...prev, [key]: value }));
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();

    if (!name.trim()) {
      toast.error("Provider name is required");
      return;
    }

    if (isEditing) {
      updateProvider.mutate(
        {
          id: provider.id,
          data: {
            name: name.trim(),
            credentials,
          },
        },
        {
          onSuccess: () => {
            toast.success("Provider updated");
            onOpenChange(false);
          },
          onError: (error) => {
            toast.error("Failed to update provider", {
              description: error.message,
            });
          },
        }
      );
    } else {
      createProvider.mutate(
        {
          provider_type: providerType,
          name: name.trim(),
          credentials,
        },
        {
          onSuccess: (newProvider) => {
            toast.success("Provider created");
            setSelectedProviderId(newProvider.id);
            onOpenChange(false);
          },
          onError: (error) => {
            toast.error("Failed to create provider", {
              description: error.message,
            });
          },
        }
      );
    }
  };

  const handleDelete = () => {
    if (!provider) return;

    if (!confirmDelete) {
      setConfirmDelete(true);
      return;
    }

    deleteProvider.mutate(provider.id, {
      onSuccess: () => {
        toast.success("Provider deleted");
        setSelectedProviderId(null);
        onOpenChange(false);
      },
      onError: (error) => {
        toast.error("Failed to delete provider", {
          description: error.message,
        });
      },
    });
  };

  const isPending =
    createProvider.isPending || updateProvider.isPending || deleteProvider.isPending;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {isEditing ? "Edit Provider" : "Add Provider"}
          </DialogTitle>
          <DialogDescription>
            {isEditing
              ? "Update the provider configuration."
              : "Configure a new messaging provider for the sandbox."}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="prov-type">Provider Type</Label>
            <Select
              id="prov-type"
              value={providerType}
              onChange={(e) => {
                setProviderType(e.target.value as ProviderType);
                setCredentials({});
              }}
              disabled={isEditing}
            >
              {(Object.keys(PROVIDER_LABELS) as ProviderType[]).map((type) => (
                <option key={type} value={type}>
                  {PROVIDER_LABELS[type]}
                </option>
              ))}
            </Select>
          </div>

          <div className="space-y-2">
            <Label htmlFor="prov-name">Name</Label>
            <Input
              id="prov-name"
              placeholder="e.g. My Telegram Bot"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>

          {credentialFields.map((field) => (
            <div key={field.key} className="space-y-2">
              <Label htmlFor={`cred-${field.key}`}>{field.label}</Label>
              <Input
                id={`cred-${field.key}`}
                type="password"
                placeholder={field.placeholder}
                value={credentials[field.key] ?? ""}
                onChange={(e) => handleCredentialChange(field.key, e.target.value)}
              />
            </div>
          ))}

          <DialogFooter>
            {isEditing && (
              <Button
                type="button"
                variant="destructive"
                onClick={handleDelete}
                disabled={isPending}
                className="mr-auto gap-1.5"
              >
                <Trash2 className="h-3.5 w-3.5" />
                {confirmDelete ? "Confirm Delete" : "Delete"}
              </Button>
            )}
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={isPending}>
              {isPending
                ? "Saving..."
                : isEditing
                  ? "Update"
                  : "Create"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export { ProviderConfigDialog };
