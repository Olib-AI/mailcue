import { useCallback, useEffect, useMemo, useRef } from "react";
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
import type { EmailDetail as EmailDetailType } from "@/types/api";
import { formatFullDate, formatEmailAddress, extractEmailAddress } from "@/lib/utils";

function buildQuotedHtml(email: EmailDetailType): string {
  const date = formatFullDate(email.date);
  const from = formatEmailAddress(email.from_address);
  const originalBody = email.html_body
    ? email.html_body
    : `<pre style="white-space: pre-wrap; margin: 0;">${(email.text_body ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")}</pre>`;

  return [
    "<br/><br/>",
    '<div style="border-left: 2px solid #ccc; padding-left: 12px; margin-left: 0; color: #666;">',
    `<p>On ${date}, ${from} wrote:</p>`,
    originalBody,
    "</div>",
  ].join("\n");
}

function buildForwardHtml(email: EmailDetailType): string {
  const date = formatFullDate(email.date);
  const from = formatEmailAddress(email.from_address);
  const to = email.to_addresses.map(formatEmailAddress).join(", ");
  const originalBody = email.html_body
    ? email.html_body
    : `<pre style="white-space: pre-wrap; margin: 0;">${(email.text_body ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")}</pre>`;

  return [
    "<br/><br/>",
    '<div style="border-left: 2px solid #ccc; padding-left: 12px; margin-left: 0; color: #666;">',
    "<p>---------- Forwarded message ----------</p>",
    `<p><strong>From:</strong> ${from}<br/>`,
    `<strong>Date:</strong> ${date}<br/>`,
    `<strong>Subject:</strong> ${email.subject}<br/>`,
    `<strong>To:</strong> ${to}</p>`,
    originalBody,
    "</div>",
  ].join("\n");
}

function prefixSubject(subject: string, prefix: "Re" | "Fwd"): string {
  const pattern = prefix === "Re" ? /^Re:\s*/i : /^Fwd:\s*/i;
  if (pattern.test(subject)) return subject;
  return `${prefix}: ${subject}`;
}

function extractRawEmail(address: string): string {
  const match = /<([^>]+)>/.exec(address);
  return match?.[1] ?? address;
}

const SIGNATURE_SEPARATOR = "<br><br>--<br>";

function buildSignatureHtml(signatureText: string): string {
  if (!signatureText) return "";
  return `${SIGNATURE_SEPARATOR}${signatureText.replace(/\n/g, "<br>")}`;
}

const composeSchema = z.object({
  from_address: z.string().min(1, "Select a sender address"),
  from_name: z.string().optional().default(""),
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
  const { composeOpen, setComposeOpen, composeContext } = useUIStore();
  const { data: mailboxData } = useMailboxes();
  const sendEmail = useSendEmail();
  const prevOpenRef = useRef(false);

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
      from_name: "",
      to_addresses: "",
      cc_addresses: "",
      subject: "",
      body: "",
      body_type: "html",
      sign: false,
      encrypt: false,
    },
  });

  const mailboxes = useMemo(
    () => mailboxData?.mailboxes ?? [],
    [mailboxData?.mailboxes]
  );

  // Track the last "from" address so we can swap signatures on change
  const lastFromRef = useRef("");

  const getSignatureForAddress = useCallback(
    (address: string): string => {
      const mb = mailboxes.find((m) => m.address === address);
      return mb?.signature ?? "";
    },
    [mailboxes]
  );

  // Pre-fill form when compose dialog opens with context
  useEffect(() => {
    const justOpened = composeOpen && !prevOpenRef.current;
    prevOpenRef.current = composeOpen;

    if (!justOpened) return;

    if (!composeContext) {
      // New compose — pre-fill with signature if a default mailbox exists
      const defaultAddress = mailboxes[0]?.address ?? "";
      const sig = buildSignatureHtml(getSignatureForAddress(defaultAddress));
      lastFromRef.current = defaultAddress;
      reset({
        from_address: defaultAddress,
        from_name: "",
        to_addresses: "",
        cc_addresses: "",
        subject: "",
        body: sig,
        body_type: "html",
        sign: false,
        encrypt: false,
      });
      return;
    }

    const { mode, originalEmail } = composeContext;
    const currentMailbox = mailboxes.find((mb) =>
      originalEmail.to_addresses.some(
        (addr) => extractRawEmail(addr).toLowerCase() === mb.address.toLowerCase()
      )
    );
    const fromAddress = currentMailbox?.address ?? "";
    lastFromRef.current = fromAddress;
    const sig = buildSignatureHtml(getSignatureForAddress(fromAddress));

    const replyToAddress = extractEmailAddress(originalEmail.from_address);

    if (mode === "reply") {
      reset({
        from_address: fromAddress,
        to_addresses: replyToAddress,
        cc_addresses: "",
        subject: prefixSubject(originalEmail.subject, "Re"),
        body: sig + buildQuotedHtml(originalEmail),
        body_type: "html",
        sign: false,
        encrypt: false,
      });
    } else if (mode === "reply-all") {
      const currentRaw = fromAddress.toLowerCase();
      const ccAddresses = [
        ...originalEmail.to_addresses,
        ...originalEmail.cc_addresses,
      ]
        .filter((addr) => extractRawEmail(addr).toLowerCase() !== currentRaw)
        .filter((addr) => extractRawEmail(addr).toLowerCase() !== extractRawEmail(originalEmail.from_address).toLowerCase())
        .join(", ");

      reset({
        from_address: fromAddress,
        to_addresses: replyToAddress,
        cc_addresses: ccAddresses,
        subject: prefixSubject(originalEmail.subject, "Re"),
        body: sig + buildQuotedHtml(originalEmail),
        body_type: "html",
        sign: false,
        encrypt: false,
      });
    } else if (mode === "forward") {
      reset({
        from_address: fromAddress,
        to_addresses: "",
        cc_addresses: "",
        subject: prefixSubject(originalEmail.subject, "Fwd"),
        body: sig + buildForwardHtml(originalEmail),
        body_type: "html",
        sign: false,
        encrypt: false,
      });
    }
  }, [composeOpen, composeContext, reset, mailboxes, getSignatureForAddress]);

  const bodyType = watch("body_type");
  const watchedFromAddress = watch("from_address");

  // Sync from_name with the selected mailbox's display_name
  useEffect(() => {
    const selectedMailbox = mailboxes.find(
      (mb) => mb.address === watchedFromAddress
    );
    setValue("from_name", selectedMailbox?.display_name ?? "");
  }, [watchedFromAddress, mailboxes, setValue]);

  // Swap signature in body when the "From" address changes
  const watchedBody = watch("body");
  useEffect(() => {
    if (!composeOpen) return;
    if (!watchedFromAddress) return;
    if (watchedFromAddress === lastFromRef.current) return;

    const oldSig = buildSignatureHtml(
      getSignatureForAddress(lastFromRef.current)
    );
    const newSig = buildSignatureHtml(
      getSignatureForAddress(watchedFromAddress)
    );
    lastFromRef.current = watchedFromAddress;

    let updatedBody = watchedBody;
    if (oldSig && updatedBody.includes(oldSig)) {
      updatedBody = updatedBody.replace(oldSig, newSig);
    } else if (!oldSig && newSig) {
      // Previous mailbox had no signature — find quoted content or append
      const quoteIdx = updatedBody.indexOf(
        '<div style="border-left: 2px solid #ccc;'
      );
      if (quoteIdx > 0) {
        updatedBody =
          updatedBody.slice(0, quoteIdx) + newSig + updatedBody.slice(quoteIdx);
      } else {
        updatedBody = updatedBody + newSig;
      }
    } else if (oldSig && !newSig) {
      // New mailbox has no signature — just remove old one (already handled by replace above returning empty)
    }

    setValue("body", updatedBody);
  }, [watchedFromAddress, composeOpen, watchedBody, getSignatureForAddress, setValue]);
  const { data: senderGpgKey } = useGpgKey(
    watchedFromAddress || undefined
  );
  const hasSenderKey = !!senderGpgKey;

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

    const isReply =
      composeContext?.mode === "reply" || composeContext?.mode === "reply-all";
    const inReplyTo = isReply
      ? composeContext.originalEmail.message_id
      : undefined;

    // Build the full References chain per RFC 2822:
    // existing References from the original email + the original email's Message-ID
    const existingRefs = isReply
      ? (composeContext.originalEmail.raw_headers?.["References"] ?? "")
          .split(/\s+/)
          .filter(Boolean)
      : [];
    const references = isReply
      ? [...existingRefs, composeContext.originalEmail.message_id]
      : undefined;

    sendEmail.mutate(
      {
        from_address: data.from_address,
        from_name: data.from_name || undefined,
        to_addresses: toList,
        cc_addresses: ccList,
        subject: data.subject,
        body: data.body,
        body_type: data.body_type,
        sign: data.sign || undefined,
        encrypt: data.encrypt || undefined,
        in_reply_to: inReplyTo,
        references: references,
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

  const dialogTitle =
    composeContext?.mode === "reply"
      ? "Reply"
      : composeContext?.mode === "reply-all"
        ? "Reply All"
        : composeContext?.mode === "forward"
          ? "Forward"
          : "New Message";

  return (
    <Dialog open={composeOpen} onOpenChange={setComposeOpen}>
      <DialogContent className="sm:max-w-[600px] max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{dialogTitle}</DialogTitle>
        </DialogHeader>

        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
          {/* From */}
          <div className="space-y-1.5">
            <Label htmlFor="from">From</Label>
            <Select id="from" {...register("from_address")}>
              <option value="">Select sender...</option>
              {mailboxes.map((mb) => (
                <option key={mb.address} value={mb.address}>
                  {mb.display_name
                    ? `${mb.display_name} <${mb.address}>`
                    : mb.address}
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
