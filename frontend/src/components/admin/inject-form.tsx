import { useState } from "react";
import { useForm, Controller } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import { Loader2, Plus, Trash2, Syringe } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Select } from "@/components/ui/select";
import { RichTextEditor } from "@/components/editor";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { useMailboxes } from "@/hooks/use-mailboxes";
import { useInjectEmail } from "@/hooks/use-emails";

const injectSchema = z.object({
  mailbox: z.string().min(1, "Select a target mailbox"),
  from_address: z.string().email("Invalid email address"),
  to_addresses: z.string().min(1, "At least one recipient is required"),
  subject: z.string().min(1, "Subject is required"),
  html_body: z.string().optional(),
  text_body: z.string().optional(),
});

type InjectFormValues = z.infer<typeof injectSchema>;

interface HeaderEntry {
  key: string;
  value: string;
}

function InjectForm() {
  const { data: mailboxData } = useMailboxes();
  const injectEmail = useInjectEmail();
  const [bodyType, setBodyType] = useState<"html" | "plain">("html");
  const [customHeaders, setCustomHeaders] = useState<HeaderEntry[]>([]);

  const {
    register,
    handleSubmit,
    reset,
    control,
    formState: { errors },
  } = useForm<InjectFormValues>({
    resolver: zodResolver(injectSchema),
    defaultValues: {
      mailbox: "",
      from_address: "noreply@example.com",
      to_addresses: "",
      subject: "",
      html_body: "",
      text_body: "",
    },
  });

  const mailboxes = mailboxData?.mailboxes ?? [];

  const addHeader = () => {
    setCustomHeaders([...customHeaders, { key: "", value: "" }]);
  };

  const removeHeader = (index: number) => {
    setCustomHeaders(customHeaders.filter((_, i) => i !== index));
  };

  const updateHeader = (
    index: number,
    field: "key" | "value",
    val: string
  ) => {
    setCustomHeaders(
      customHeaders.map((h, i) => (i === index ? { ...h, [field]: val } : h))
    );
  };

  const onSubmit = (data: InjectFormValues) => {
    const headers: Record<string, string> = {};
    for (const h of customHeaders) {
      if (h.key.trim()) {
        headers[h.key.trim()] = h.value;
      }
    }

    injectEmail.mutate(
      {
        mailbox: data.mailbox,
        from_address: data.from_address,
        to_addresses: data.to_addresses
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
        subject: data.subject,
        html_body: bodyType === "html" ? data.html_body : undefined,
        text_body: bodyType === "plain" ? data.text_body : undefined,
        headers: Object.keys(headers).length > 0 ? headers : undefined,
      },
      {
        onSuccess: () => {
          toast.success("Email injected successfully");
          reset();
          setCustomHeaders([]);
        },
        onError: (err) => {
          toast.error(
            err instanceof Error ? err.message : "Failed to inject email"
          );
        },
      }
    );
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold tracking-tight">Inject Email</h2>
        <p className="text-sm text-muted-foreground">
          Inject a test email directly into a mailbox via IMAP APPEND
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Form */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Configuration</CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
              {/* Target Mailbox */}
              <div className="space-y-1.5">
                <Label htmlFor="inject-mailbox">Target Mailbox</Label>
                <Select id="inject-mailbox" {...register("mailbox")}>
                  <option value="">Select mailbox...</option>
                  {mailboxes.map((mb) => (
                    <option key={mb.address} value={mb.address}>
                      {mb.address}
                    </option>
                  ))}
                </Select>
                {errors.mailbox && (
                  <p className="text-xs text-destructive">
                    {errors.mailbox.message}
                  </p>
                )}
              </div>

              {/* From */}
              <div className="space-y-1.5">
                <Label htmlFor="inject-from">From</Label>
                <Input
                  id="inject-from"
                  placeholder="noreply@myapp.com"
                  {...register("from_address")}
                />
                {errors.from_address && (
                  <p className="text-xs text-destructive">
                    {errors.from_address.message}
                  </p>
                )}
              </div>

              {/* To */}
              <div className="space-y-1.5">
                <Label htmlFor="inject-to">To</Label>
                <Input
                  id="inject-to"
                  placeholder="user@mailcue.local (comma-separated)"
                  {...register("to_addresses")}
                />
                {errors.to_addresses && (
                  <p className="text-xs text-destructive">
                    {errors.to_addresses.message}
                  </p>
                )}
              </div>

              {/* Subject */}
              <div className="space-y-1.5">
                <Label htmlFor="inject-subject">Subject</Label>
                <Input
                  id="inject-subject"
                  placeholder="Test email subject"
                  {...register("subject")}
                />
                {errors.subject && (
                  <p className="text-xs text-destructive">
                    {errors.subject.message}
                  </p>
                )}
              </div>

              <Separator />

              {/* Body Type Toggle */}
              <div className="flex items-center gap-4">
                <Label>Body Type</Label>
                <div className="flex rounded-md border">
                  <button
                    type="button"
                    className={`px-3 py-1 text-sm rounded-l-md transition-colors ${
                      bodyType === "html"
                        ? "bg-primary text-primary-foreground"
                        : "hover:bg-muted"
                    }`}
                    onClick={() => setBodyType("html")}
                  >
                    HTML
                  </button>
                  <button
                    type="button"
                    className={`px-3 py-1 text-sm rounded-r-md transition-colors ${
                      bodyType === "plain"
                        ? "bg-primary text-primary-foreground"
                        : "hover:bg-muted"
                    }`}
                    onClick={() => setBodyType("plain")}
                  >
                    Plain Text
                  </button>
                </div>
              </div>

              {/* Body */}
              {bodyType === "html" ? (
                <div className="space-y-1.5">
                  <Label>HTML Body</Label>
                  <Controller
                    name="html_body"
                    control={control}
                    render={({ field }) => (
                      <RichTextEditor
                        value={field.value || ""}
                        onChange={field.onChange}
                        mode="html"
                        placeholder="<p>Hello, this is a test email.</p>"
                      />
                    )}
                  />
                </div>
              ) : (
                <div className="space-y-1.5">
                  <Label htmlFor="inject-text">Plain Text Body</Label>
                  <Textarea
                    id="inject-text"
                    placeholder="Hello, this is a test email."
                    rows={8}
                    className="font-mono text-sm"
                    {...register("text_body")}
                  />
                </div>
              )}

              <Separator />

              {/* Custom Headers */}
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <Label>Custom Headers</Label>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={addHeader}
                  >
                    <Plus className="mr-1.5 h-3 w-3" />
                    Add Header
                  </Button>
                </div>
                {customHeaders.map((header, index) => (
                  <div key={index} className="flex items-center gap-2">
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

              {/* Submit */}
              <Button
                type="submit"
                className="w-full"
                disabled={injectEmail.isPending}
              >
                {injectEmail.isPending ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <Syringe className="mr-2 h-4 w-4" />
                )}
                Inject Email
              </Button>
            </form>
          </CardContent>
        </Card>

        {/* Info / Help Card */}
        <Card className="h-fit">
          <CardHeader>
            <CardTitle className="text-base">About Email Injection</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4 text-sm text-muted-foreground">
            <p>
              Email injection bypasses SMTP entirely. The email is created
              directly in the target mailbox via IMAP APPEND, making it
              instantly available for testing.
            </p>
            <div>
              <h4 className="font-medium text-foreground mb-1">Use Cases</h4>
              <ul className="list-disc list-inside space-y-1">
                <li>
                  Test how your application handles specific email formats
                </li>
                <li>Inject emails with custom headers for testing</li>
                <li>
                  Create reproducible test scenarios without SMTP delivery
                </li>
                <li>Test HTML email rendering in the web UI</li>
              </ul>
            </div>
            <div>
              <h4 className="font-medium text-foreground mb-1">
                API Endpoint
              </h4>
              <code className="block rounded bg-muted px-2 py-1 text-xs font-mono">
                POST /api/v1/emails/inject
              </code>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

export { InjectForm };
