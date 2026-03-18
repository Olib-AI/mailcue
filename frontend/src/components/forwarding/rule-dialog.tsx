import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import { Loader2, Plus, Trash2, FlaskConical } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
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
  useCreateForwardingRule,
  useUpdateForwardingRule,
  useTestForwardingRule,
} from "@/hooks/use-forwarding-rules";
import { useMailboxes } from "@/hooks/use-mailboxes";
import type {
  ForwardingRule,
  ForwardingRuleActionType,
} from "@/types/api";

// --- Zod Schema ---

const headerPairSchema = z.object({
  key: z.string().min(1, "Header name is required"),
  value: z.string().min(1, "Header value is required"),
});

const ruleFormSchema = z
  .object({
    name: z.string().min(1, "Rule name is required"),
    enabled: z.boolean(),
    match_from: z.string(),
    match_to: z.string(),
    match_subject: z.string(),
    match_mailbox: z.string(),
    action_type: z.enum(["smtp_forward", "webhook"]),
    smtp_to_address: z.string(),
    webhook_url: z.string(),
    webhook_method: z.string(),
    webhook_headers: z.array(headerPairSchema).or(z.array(z.any())),
  })
  .superRefine((data, ctx) => {
    if (data.action_type === "smtp_forward") {
      if (!data.smtp_to_address) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: "Forward-to address is required",
          path: ["smtp_to_address"],
        });
      } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(data.smtp_to_address)) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: "Must be a valid email address",
          path: ["smtp_to_address"],
        });
      }
    }
    if (data.action_type === "webhook") {
      if (!data.webhook_url) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: "Webhook URL is required",
          path: ["webhook_url"],
        });
      } else {
        try {
          new URL(data.webhook_url);
        } catch {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            message: "Must be a valid URL",
            path: ["webhook_url"],
          });
        }
      }
    }
  });

type RuleFormValues = z.infer<typeof ruleFormSchema>;

// --- Props ---

interface RuleDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  rule: ForwardingRule | null;
}

// --- Helpers ---

function buildDefaults(rule: ForwardingRule | null): RuleFormValues {
  if (!rule) {
    return {
      name: "",
      enabled: true,
      match_from: "",
      match_to: "",
      match_subject: "",
      match_mailbox: "",
      action_type: "smtp_forward",
      smtp_to_address: "",
      webhook_url: "",
      webhook_method: "POST",
      webhook_headers: [],
    };
  }

  const headers = Object.entries(rule.action_config.headers ?? {}).map(
    ([key, value]) => ({ key, value })
  );

  return {
    name: rule.name,
    enabled: rule.enabled,
    match_from: rule.match_from ?? "",
    match_to: rule.match_to ?? "",
    match_subject: rule.match_subject ?? "",
    match_mailbox: rule.match_mailbox ?? "",
    action_type: rule.action_type,
    smtp_to_address: rule.action_config.to_address ?? "",
    webhook_url: rule.action_config.url ?? "",
    webhook_method: rule.action_config.method ?? "POST",
    webhook_headers: headers,
  };
}

// --- Component ---

function RuleDialog({ open, onOpenChange, rule }: RuleDialogProps) {
  const isEditing = rule !== null;
  const createRule = useCreateForwardingRule();
  const updateRule = useUpdateForwardingRule();
  const testRule = useTestForwardingRule();

  const { data: mailboxData } = useMailboxes();
  const mailboxes = mailboxData?.mailboxes ?? [];

  const {
    register,
    handleSubmit,
    reset,
    watch,
    setValue,
    formState: { errors },
  } = useForm<RuleFormValues>({
    resolver: zodResolver(ruleFormSchema),
    defaultValues: buildDefaults(rule),
  });

  const actionType = watch("action_type") as ForwardingRuleActionType;
  const enabledValue = watch("enabled");

  // Track webhook headers locally for dynamic add/remove
  const [headers, setHeaders] = useState<{ key: string; value: string }[]>([]);

  // Reset form when dialog opens/rule changes
  useEffect(() => {
    if (open) {
      const defaults = buildDefaults(rule);
      reset(defaults);
      const h = Object.entries(rule?.action_config.headers ?? {}).map(
        ([key, value]) => ({ key, value })
      );
      setHeaders(rule ? h : []);
    }
  }, [open, rule, reset]);

  // Sync headers state to form
  useEffect(() => {
    setValue("webhook_headers", headers);
  }, [headers, setValue]);

  const addHeader = () => {
    setHeaders((prev) => [...prev, { key: "", value: "" }]);
  };

  const removeHeader = (index: number) => {
    setHeaders((prev) => prev.filter((_, i) => i !== index));
  };

  const updateHeader = (
    index: number,
    field: "key" | "value",
    val: string
  ) => {
    setHeaders((prev) =>
      prev.map((h, i) => (i === index ? { ...h, [field]: val } : h))
    );
  };

  const onSubmit = (values: RuleFormValues) => {
    const payload = {
      name: values.name,
      enabled: values.enabled,
      match_from: values.match_from || null,
      match_to: values.match_to || null,
      match_subject: values.match_subject || null,
      match_mailbox: values.match_mailbox || null,
      action_type: values.action_type,
      action_config:
        values.action_type === "smtp_forward"
          ? { to_address: values.smtp_to_address }
          : {
              url: values.webhook_url,
              method: values.webhook_method || "POST",
              headers: Object.fromEntries(
                headers
                  .filter((h) => h.key.trim() !== "")
                  .map((h) => [h.key, h.value])
              ),
            },
    };

    if (isEditing) {
      updateRule.mutate(
        { id: rule.id, data: payload },
        {
          onSuccess: () => {
            toast.success(`Rule "${values.name}" updated`);
            onOpenChange(false);
          },
          onError: (err) => {
            toast.error(
              err instanceof Error ? err.message : "Failed to update rule"
            );
          },
        }
      );
    } else {
      createRule.mutate(payload, {
        onSuccess: () => {
          toast.success(`Rule "${values.name}" created`);
          onOpenChange(false);
        },
        onError: (err) => {
          toast.error(
            err instanceof Error ? err.message : "Failed to create rule"
          );
        },
      });
    }
  };

  const handleTest = () => {
    if (!rule) return;
    testRule.mutate(rule.id, {
      onSuccess: (result) => {
        if (result.matched) {
          toast.success(`Test passed: ${result.details}`);
        } else {
          toast.info(`Test result: ${result.details}`);
        }
      },
      onError: (err) => {
        toast.error(
          err instanceof Error ? err.message : "Failed to test rule"
        );
      },
    });
  };

  const isPending = createRule.isPending || updateRule.isPending;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {isEditing ? "Edit Forwarding Rule" : "Create Forwarding Rule"}
          </DialogTitle>
          <DialogDescription>
            {isEditing
              ? "Update the rule configuration below."
              : "Define match patterns and the forwarding action."}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit(onSubmit)} className="space-y-5">
          {/* Name + Enabled */}
          <div className="space-y-1.5">
            <Label htmlFor="rule-name">Name</Label>
            <Input
              id="rule-name"
              placeholder="e.g. Forward support emails"
              autoFocus
              {...register("name")}
            />
            {errors.name && (
              <p className="text-xs text-destructive">
                {errors.name.message}
              </p>
            )}
          </div>

          <div className="flex items-center gap-2">
            <Checkbox
              checked={enabledValue}
              onCheckedChange={(checked) => setValue("enabled", checked)}
            />
            <Label className="cursor-pointer" onClick={() => setValue("enabled", !enabledValue)}>
              Enabled
            </Label>
          </div>

          {/* Match Patterns */}
          <div className="space-y-3">
            <h3 className="text-sm font-semibold">Match Patterns</h3>
            <p className="text-xs text-muted-foreground">
              All patterns are optional regex. Leave blank to match everything.
            </p>

            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="rule-match-from">
                  From pattern{" "}
                  <span className="text-muted-foreground font-normal">
                    (regex)
                  </span>
                </Label>
                <Input
                  id="rule-match-from"
                  placeholder=".*@example\.com"
                  {...register("match_from")}
                />
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="rule-match-to">
                  To pattern{" "}
                  <span className="text-muted-foreground font-normal">
                    (regex)
                  </span>
                </Label>
                <Input
                  id="rule-match-to"
                  placeholder="support@.*"
                  {...register("match_to")}
                />
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="rule-match-subject">
                  Subject pattern{" "}
                  <span className="text-muted-foreground font-normal">
                    (regex)
                  </span>
                </Label>
                <Input
                  id="rule-match-subject"
                  placeholder="URGENT.*"
                  {...register("match_subject")}
                />
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="rule-match-mailbox">
                  Mailbox{" "}
                  <span className="text-muted-foreground font-normal">
                    (optional)
                  </span>
                </Label>
                <Select id="rule-match-mailbox" {...register("match_mailbox")}>
                  <option value="">Any mailbox</option>
                  {mailboxes.map((mb) => (
                    <option key={mb.address} value={mb.address}>
                      {mb.address}
                    </option>
                  ))}
                </Select>
              </div>
            </div>
          </div>

          {/* Action */}
          <div className="space-y-3">
            <h3 className="text-sm font-semibold">Action</h3>

            <div className="space-y-1.5">
              <Label htmlFor="rule-action-type">Action type</Label>
              <Select id="rule-action-type" {...register("action_type")}>
                <option value="smtp_forward">SMTP Forward</option>
                <option value="webhook">Webhook</option>
              </Select>
            </div>

            {actionType === "smtp_forward" && (
              <div className="space-y-1.5">
                <Label htmlFor="rule-smtp-to">Forward to address</Label>
                <Input
                  id="rule-smtp-to"
                  type="email"
                  placeholder="forward@example.com"
                  {...register("smtp_to_address")}
                />
                {errors.smtp_to_address && (
                  <p className="text-xs text-destructive">
                    {errors.smtp_to_address.message}
                  </p>
                )}
              </div>
            )}

            {actionType === "webhook" && (
              <div className="space-y-3">
                <div className="space-y-1.5">
                  <Label htmlFor="rule-webhook-url">Webhook URL</Label>
                  <Input
                    id="rule-webhook-url"
                    placeholder="https://example.com/webhook"
                    {...register("webhook_url")}
                  />
                  {errors.webhook_url && (
                    <p className="text-xs text-destructive">
                      {errors.webhook_url.message}
                    </p>
                  )}
                </div>

                <div className="space-y-1.5">
                  <Label htmlFor="rule-webhook-method">HTTP Method</Label>
                  <Select
                    id="rule-webhook-method"
                    {...register("webhook_method")}
                  >
                    <option value="POST">POST</option>
                    <option value="PUT">PUT</option>
                    <option value="PATCH">PATCH</option>
                  </Select>
                </div>

                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <Label>
                      Custom Headers{" "}
                      <span className="text-muted-foreground font-normal">
                        (optional)
                      </span>
                    </Label>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={addHeader}
                    >
                      <Plus className="mr-1 h-3 w-3" />
                      Add
                    </Button>
                  </div>
                  {headers.map((header, index) => (
                    <div
                      key={index}
                      className="flex items-center gap-2"
                    >
                      <Input
                        placeholder="Header name"
                        value={header.key}
                        onChange={(e) =>
                          updateHeader(index, "key", e.target.value)
                        }
                        className="flex-1"
                      />
                      <Input
                        placeholder="Value"
                        value={header.value}
                        onChange={(e) =>
                          updateHeader(index, "value", e.target.value)
                        }
                        className="flex-1"
                      />
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        className="h-9 w-9 shrink-0 text-muted-foreground hover:text-destructive"
                        onClick={() => removeHeader(index)}
                        aria-label="Remove header"
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          <DialogFooter>
            {isEditing && (
              <Button
                type="button"
                variant="outline"
                onClick={handleTest}
                disabled={testRule.isPending}
                className="mr-auto"
              >
                {testRule.isPending ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <FlaskConical className="mr-2 h-4 w-4" />
                )}
                Test
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
              {isPending && (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              )}
              {isEditing ? "Save Changes" : "Create Rule"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export { RuleDialog };
