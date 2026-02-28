import { useForm, Controller } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Loader2, X } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { RichTextEditor } from "@/components/editor";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useUIStore } from "@/stores/ui-store";
import { useMailboxes } from "@/hooks/use-mailboxes";
import { useSendEmail } from "@/hooks/use-emails";
import { useGpgKey } from "@/hooks/use-gpg";

const composeSchema = z.object({
  from_address: z.string().min(1, "Select a sender address"),
  to_addresses: z.string().min(1, "At least one recipient is required"),
  cc_addresses: z.string().optional(),
  subject: z.string().min(1, "Subject is required"),
  body: z.string().min(1, "Message body is required"),
  body_type: z.enum(["html", "plain"]),
  sign: z.boolean(),
  encrypt: z.boolean(),
});

type ComposeFormValues = z.infer<typeof composeSchema>;

function ComposeDialog() {
  const { composeOpen, setComposeOpen } = useUIStore();
  const { data: mailboxData } = useMailboxes();
  const sendEmail = useSendEmail();

  const {
    register,
    handleSubmit,
    reset,
    watch,
    control,
    setValue,
    formState: { errors },
  } = useForm<ComposeFormValues>({
    resolver: zodResolver(composeSchema),
    defaultValues: {
      from_address: "",
      to_addresses: "",
      cc_addresses: "",
      subject: "",
      body: "",
      body_type: "html",
      sign: false,
      encrypt: false,
    },
  });

  const bodyType = watch("body_type");
  const watchedFromAddress = watch("from_address");
  const { data: senderGpgKey } = useGpgKey(
    watchedFromAddress || undefined
  );
  const hasSenderKey = !!senderGpgKey;

  const mailboxes = mailboxData?.mailboxes ?? [];

  const onSubmit = (data: ComposeFormValues) => {
    const toList = data.to_addresses
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    const ccList = data.cc_addresses
      ? data.cc_addresses
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean)
      : undefined;

    sendEmail.mutate(
      {
        from_address: data.from_address,
        to_addresses: toList,
        cc_addresses: ccList,
        subject: data.subject,
        body: data.body,
        body_type: data.body_type,
        sign: data.sign || undefined,
        encrypt: data.encrypt || undefined,
      },
      {
        onSuccess: () => {
          toast.success("Email sent successfully");
          reset();
          setComposeOpen(false);
        },
        onError: (err) => {
          toast.error(
            err instanceof Error ? err.message : "Failed to send email"
          );
        },
      }
    );
  };

  return (
    <Dialog open={composeOpen} onOpenChange={setComposeOpen}>
      <DialogContent className="sm:max-w-[600px] max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>New Message</DialogTitle>
        </DialogHeader>

        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
          {/* From */}
          <div className="space-y-1.5">
            <Label htmlFor="from">From</Label>
            <Select id="from" {...register("from_address")}>
              <option value="">Select sender...</option>
              {mailboxes.map((mb) => (
                <option key={mb.address} value={mb.address}>
                  {mb.address}
                </option>
              ))}
            </Select>
            {errors.from_address && (
              <p className="text-xs text-destructive">
                {errors.from_address.message}
              </p>
            )}
          </div>

          {/* To */}
          <div className="space-y-1.5">
            <Label htmlFor="to">To</Label>
            <Input
              id="to"
              placeholder="recipient@example.com (comma-separated)"
              {...register("to_addresses")}
            />
            {errors.to_addresses && (
              <p className="text-xs text-destructive">
                {errors.to_addresses.message}
              </p>
            )}
          </div>

          {/* CC */}
          <div className="space-y-1.5">
            <Label htmlFor="cc">CC</Label>
            <Input
              id="cc"
              placeholder="cc@example.com (optional)"
              {...register("cc_addresses")}
            />
          </div>

          {/* Subject */}
          <div className="space-y-1.5">
            <Label htmlFor="subject">Subject</Label>
            <Input
              id="subject"
              placeholder="Email subject"
              {...register("subject")}
            />
            {errors.subject && (
              <p className="text-xs text-destructive">
                {errors.subject.message}
              </p>
            )}
          </div>

          {/* Body */}
          <div className="space-y-1.5">
            <Label>Body</Label>
            <Controller
              name="body"
              control={control}
              render={({ field }) => (
                <RichTextEditor
                  value={field.value}
                  onChange={field.onChange}
                  mode={bodyType}
                  onModeChange={(m) => setValue("body_type", m)}
                  placeholder="Type your message..."
                />
              )}
            />
            {errors.body && (
              <p className="text-xs text-destructive">
                {errors.body.message}
              </p>
            )}
          </div>

          {/* GPG Options */}
          <div className="flex items-center gap-6 rounded-md border p-3">
            <label
              className="flex items-center gap-2 text-sm"
              title={
                hasSenderKey
                  ? "Sign this email with the sender's GPG key"
                  : "No GPG key available for the selected sender"
              }
            >
              <input
                type="checkbox"
                className="h-4 w-4 rounded border-input"
                disabled={!hasSenderKey}
                {...register("sign")}
              />
              <span
                className={
                  hasSenderKey
                    ? "text-foreground"
                    : "text-muted-foreground"
                }
              >
                Sign
              </span>
              {!hasSenderKey && watchedFromAddress && (
                <span className="text-xs text-muted-foreground">
                  (no key)
                </span>
              )}
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                className="h-4 w-4 rounded border-input"
                {...register("encrypt")}
              />
              <span className="text-foreground">Encrypt</span>
            </label>
          </div>

          {/* Actions */}
          <div className="flex justify-end gap-2 pt-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                reset();
                setComposeOpen(false);
              }}
            >
              <X className="mr-1.5 h-4 w-4" />
              Discard
            </Button>
            <Button type="submit" disabled={sendEmail.isPending}>
              {sendEmail.isPending && (
                <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
              )}
              Send
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export { ComposeDialog };
