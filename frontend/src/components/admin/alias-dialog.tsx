import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  useCreateAlias,
  useUpdateAlias,
} from "@/hooks/use-aliases";
import type { Alias } from "@/types/api";

// --- Zod Schema ---

const aliasFormSchema = z.object({
  source_address: z.string().min(1, "Source address is required"),
  destination_address: z
    .string()
    .min(1, "Destination address is required")
    .regex(/^[^\s@]+@[^\s@]+\.[^\s@]+$/, "Must be a valid email address"),
  is_catch_all: z.boolean(),
  enabled: z.boolean(),
});

type AliasFormValues = z.infer<typeof aliasFormSchema>;

// --- Props ---

interface AliasDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  alias: Alias | null;
}

// --- Helpers ---

function buildDefaults(alias: Alias | null): AliasFormValues {
  if (!alias) {
    return {
      source_address: "",
      destination_address: "",
      is_catch_all: false,
      enabled: true,
    };
  }

  return {
    source_address: alias.source_address,
    destination_address: alias.destination_address,
    is_catch_all: alias.is_catch_all,
    enabled: alias.enabled,
  };
}

// --- Component ---

function AliasDialog({ open, onOpenChange, alias }: AliasDialogProps) {
  const isEditing = alias !== null;
  const createAlias = useCreateAlias();
  const updateAlias = useUpdateAlias();

  const {
    register,
    handleSubmit,
    reset,
    watch,
    setValue,
    formState: { errors },
  } = useForm<AliasFormValues>({
    resolver: zodResolver(aliasFormSchema),
    defaultValues: buildDefaults(alias),
  });

  const enabledValue = watch("enabled");
  const isCatchAllValue = watch("is_catch_all");

  // Reset form when dialog opens/alias changes
  useEffect(() => {
    if (open) {
      reset(buildDefaults(alias));
    }
  }, [open, alias, reset]);

  const onSubmit = (values: AliasFormValues) => {
    if (isEditing) {
      updateAlias.mutate(
        { id: alias.id, data: values },
        {
          onSuccess: () => {
            toast.success("Alias updated");
            onOpenChange(false);
          },
          onError: (err) => {
            toast.error(
              err instanceof Error ? err.message : "Failed to update alias"
            );
          },
        }
      );
    } else {
      createAlias.mutate(values, {
        onSuccess: () => {
          toast.success("Alias created");
          onOpenChange(false);
        },
        onError: (err) => {
          toast.error(
            err instanceof Error ? err.message : "Failed to create alias"
          );
        },
      });
    }
  };

  const isPending = createAlias.isPending || updateAlias.isPending;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>
            {isEditing ? "Edit Alias" : "Create Alias"}
          </DialogTitle>
          <DialogDescription>
            {isEditing
              ? "Update the email alias configuration."
              : "Create a new email alias to route messages."}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="alias-source">Source Address</Label>
            <Input
              id="alias-source"
              placeholder="info@example.com"
              autoFocus
              {...register("source_address")}
            />
            {errors.source_address && (
              <p className="text-xs text-destructive">
                {errors.source_address.message}
              </p>
            )}
            <p className="text-xs text-muted-foreground">
              The address that receives email (or a pattern for catch-all)
            </p>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="alias-destination">Destination Address</Label>
            <Input
              id="alias-destination"
              type="email"
              placeholder="user@example.com"
              {...register("destination_address")}
            />
            {errors.destination_address && (
              <p className="text-xs text-destructive">
                {errors.destination_address.message}
              </p>
            )}
            <p className="text-xs text-muted-foreground">
              The mailbox where messages will be delivered
            </p>
          </div>

          <div className="flex items-center gap-2">
            <Checkbox
              checked={isCatchAllValue}
              onCheckedChange={(checked) => setValue("is_catch_all", checked)}
            />
            <Label
              className="cursor-pointer"
              onClick={() => setValue("is_catch_all", !isCatchAllValue)}
            >
              Catch-all
            </Label>
            <span className="text-xs text-muted-foreground">
              Match all addresses on the domain
            </span>
          </div>

          <div className="flex items-center gap-2">
            <Checkbox
              checked={enabledValue}
              onCheckedChange={(checked) => setValue("enabled", checked)}
            />
            <Label
              className="cursor-pointer"
              onClick={() => setValue("enabled", !enabledValue)}
            >
              Enabled
            </Label>
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={isPending}>
              {isPending && (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              )}
              {isEditing ? "Save Changes" : "Create Alias"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export { AliasDialog };
