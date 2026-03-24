import { useCallback } from "react";
import { useSearchParams } from "react-router-dom";
import {
  Copy,
  Check,
  Terminal,
  Plug,
  BookOpen,
  Code2,
  Server,
  ExternalLink,
  Loader2,
  Download,
  Bot,
} from "lucide-react";
import { toast } from "sonner";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useServerSettings } from "@/hooks/use-server-settings";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function useClipboard() {
  return useCallback((text: string, label?: string) => {
    void navigator.clipboard.writeText(text).then(() => {
      toast.success(label ? `${label} copied` : "Copied to clipboard");
    });
  }, []);
}

function getHost(): string {
  return window.location.hostname;
}

function getOrigin(): string {
  return window.location.origin;
}

// ---------------------------------------------------------------------------
// Small reusable pieces
// ---------------------------------------------------------------------------

interface CopyFieldProps {
  label: string;
  value: string;
  mono?: boolean;
}

function CopyField({ label, value, mono = true }: CopyFieldProps) {
  const copy = useClipboard();

  return (
    <div className="flex items-center justify-between gap-4 py-1.5">
      <span className="text-sm text-muted-foreground shrink-0">{label}</span>
      <div className="flex items-center gap-2 min-w-0">
        <span
          className={`text-sm truncate ${mono ? "font-mono" : "font-medium"}`}
        >
          {value}
        </span>
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7 shrink-0"
          onClick={() => copy(value, label)}
          aria-label={`Copy ${label}`}
        >
          <Copy className="h-3.5 w-3.5" />
        </Button>
      </div>
    </div>
  );
}

interface MethodBadgeProps {
  method: "GET" | "POST" | "PUT" | "DELETE" | "PATCH";
}

function MethodBadge({ method }: MethodBadgeProps) {
  const colors: Record<string, string> = {
    GET: "bg-emerald-600 text-white",
    POST: "bg-blue-600 text-white",
    PUT: "bg-amber-600 text-white",
    DELETE: "bg-red-600 text-white",
    PATCH: "bg-purple-600 text-white",
  };

  return (
    <span
      className={`inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-bold tracking-wider ${colors[method] ?? ""}`}
    >
      {method}
    </span>
  );
}

interface CodeBlockProps {
  code: string;
  language: string;
}

function CodeBlock({ code, language }: CodeBlockProps) {
  const copy = useClipboard();

  return (
    <div className="relative rounded-lg border bg-muted/50">
      <div className="flex items-center justify-between border-b px-4 py-2">
        <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
          {language}
        </span>
        <Button
          variant="ghost"
          size="sm"
          className="h-7 gap-1.5 text-xs"
          onClick={() => copy(code, `${language} snippet`)}
        >
          <Copy className="h-3 w-3" />
          Copy
        </Button>
      </div>
      <pre className="overflow-x-auto p-4 text-xs leading-relaxed font-mono">
        <code>{code}</code>
      </pre>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab 1 — Connection Info
// ---------------------------------------------------------------------------

function ConnectionInfoTab() {
  const host = getHost();
  const origin = getOrigin();
  const copy = useClipboard();

  const smtpJson = JSON.stringify(
    {
      host,
      ports: { smtp: 25, submission: 587 },
      security: "STARTTLS",
      auth: { username: "<mailbox>@<domain>", password: "<mailbox-password>" },
    },
    null,
    2
  );

  const imapJson = JSON.stringify(
    {
      host,
      ports: { starttls: 143, ssl: 993 },
      security: "STARTTLS / SSL",
      username: "<mailbox>@<domain>",
    },
    null,
    2
  );

  const pop3Json = JSON.stringify(
    { host, ports: { starttls: 110, ssl: 995 }, security: "STARTTLS / SSL" },
    null,
    2
  );

  return (
    <div className="grid gap-4 md:grid-cols-2">
      {/* SMTP */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center gap-2">
            <Plug className="h-4 w-4" />
            SMTP
          </CardTitle>
          <CardDescription>Send emails from your application</CardDescription>
        </CardHeader>
        <CardContent className="space-y-0.5">
          <CopyField label="Host" value={host} />
          <CopyField label="Port (SMTP)" value="25" />
          <CopyField label="Port (Submission)" value="587" />
          <CopyField label="Security" value="STARTTLS" mono={false} />
          <CopyField
            label="Username"
            value="<mailbox>@<domain>"
          />
          <CopyField label="Password" value="<mailbox-password>" />
          <div className="pt-3">
            <Button
              variant="outline"
              size="sm"
              className="w-full text-xs"
              onClick={() => copy(smtpJson, "SMTP config JSON")}
            >
              <Copy className="mr-1.5 h-3 w-3" />
              Copy as JSON
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* IMAP */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center gap-2">
            <Plug className="h-4 w-4" />
            IMAP
          </CardTitle>
          <CardDescription>Read emails with IMAP client</CardDescription>
        </CardHeader>
        <CardContent className="space-y-0.5">
          <CopyField label="Host" value={host} />
          <CopyField label="Port (STARTTLS)" value="143" />
          <CopyField label="Port (SSL/TLS)" value="993" />
          <CopyField
            label="Username"
            value="<mailbox>@<domain>"
          />
          <div className="pt-3">
            <Button
              variant="outline"
              size="sm"
              className="w-full text-xs"
              onClick={() => copy(imapJson, "IMAP config JSON")}
            >
              <Copy className="mr-1.5 h-3 w-3" />
              Copy as JSON
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* POP3 */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center gap-2">
            <Plug className="h-4 w-4" />
            POP3
          </CardTitle>
          <CardDescription>Download emails with POP3</CardDescription>
        </CardHeader>
        <CardContent className="space-y-0.5">
          <CopyField label="Host" value={host} />
          <CopyField label="Port (STARTTLS)" value="110" />
          <CopyField label="Port (SSL/TLS)" value="995" />
          <div className="pt-3">
            <Button
              variant="outline"
              size="sm"
              className="w-full text-xs"
              onClick={() => copy(pop3Json, "POP3 config JSON")}
            >
              <Copy className="mr-1.5 h-3 w-3" />
              Copy as JSON
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* API */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center gap-2">
            <Code2 className="h-4 w-4" />
            REST API
          </CardTitle>
          <CardDescription>Programmatic access via HTTP</CardDescription>
        </CardHeader>
        <CardContent className="space-y-0.5">
          <CopyField label="Base URL" value={`${origin}/api/v1`} />
          <CopyField
            label="Auth (Bearer)"
            value="Authorization: Bearer <token>"
          />
          <CopyField
            label="Auth (API Key)"
            value="X-API-Key: <your-api-key>"
          />
          <div className="pt-3">
            <Button
              variant="outline"
              size="sm"
              className="w-full text-xs"
              onClick={() =>
                window.open(`${origin}/api/docs`, "_blank", "noopener")
              }
            >
              <ExternalLink className="mr-1.5 h-3 w-3" />
              Open Swagger Docs
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab 2 — API Reference
// ---------------------------------------------------------------------------

interface Endpoint {
  method: "GET" | "POST" | "PUT" | "DELETE";
  path: string;
  description: string;
}

const API_ENDPOINTS: Record<string, Endpoint[]> = {
  Auth: [
    { method: "POST", path: "/auth/login", description: "Authenticate and receive JWT tokens" },
    { method: "POST", path: "/auth/refresh", description: "Refresh access token using cookie" },
    { method: "POST", path: "/auth/logout", description: "Invalidate session" },
    { method: "GET", path: "/auth/me", description: "Get current user profile" },
    { method: "PUT", path: "/auth/password", description: "Change password" },
    { method: "POST", path: "/auth/totp/setup", description: "Begin TOTP 2FA setup" },
    { method: "POST", path: "/auth/totp/verify", description: "Verify TOTP code" },
    { method: "POST", path: "/auth/totp/disable", description: "Disable 2FA" },
  ],
  Emails: [
    { method: "GET", path: "/emails", description: "List emails for a mailbox and folder" },
    { method: "GET", path: "/emails/:id", description: "Get email by ID with full body" },
    { method: "POST", path: "/emails/send", description: "Send an email via SMTP" },
    { method: "PUT", path: "/emails/:id/read", description: "Mark email as read/unread" },
    { method: "PUT", path: "/emails/:id/move", description: "Move email to another folder" },
    { method: "DELETE", path: "/emails/:id", description: "Delete a single email" },
    { method: "POST", path: "/emails/bulk-delete", description: "Bulk delete emails" },
    { method: "DELETE", path: "/emails/purge", description: "Purge all in folder" },
    { method: "POST", path: "/emails/inject", description: "Inject a raw email into a mailbox" },
  ],
  Mailboxes: [
    { method: "GET", path: "/mailboxes", description: "List all mailboxes" },
    { method: "POST", path: "/mailboxes", description: "Create a new mailbox" },
    { method: "DELETE", path: "/mailboxes/:address", description: "Delete a mailbox" },
  ],
  "GPG Keys": [
    { method: "GET", path: "/gpg/keys", description: "List GPG keys for a mailbox" },
    { method: "POST", path: "/gpg/keys/generate", description: "Generate a new GPG key pair" },
    { method: "POST", path: "/gpg/keys/import", description: "Import an existing GPG key" },
    { method: "DELETE", path: "/gpg/keys/:fingerprint", description: "Delete a GPG key" },
    { method: "GET", path: "/gpg/keys/:fingerprint/export", description: "Export public key" },
  ],
  Domains: [
    { method: "GET", path: "/domains", description: "List configured domains" },
    { method: "POST", path: "/domains", description: "Add a domain" },
    { method: "DELETE", path: "/domains/:domain", description: "Remove a domain" },
    { method: "GET", path: "/domains/:domain/dns-check", description: "Check DNS records" },
  ],
  System: [
    { method: "GET", path: "/system/settings", description: "Get server settings" },
    { method: "PUT", path: "/system/settings", description: "Update server settings" },
    { method: "GET", path: "/system/certificate", description: "Get TLS certificate info" },
    { method: "POST", path: "/system/certificate/upload", description: "Upload TLS certificate" },
    { method: "POST", path: "/system/certificate/generate", description: "Generate self-signed cert" },
  ],
  "API Keys": [
    { method: "GET", path: "/auth/api-keys", description: "List your API keys" },
    { method: "POST", path: "/auth/api-keys", description: "Create a new API key" },
    { method: "DELETE", path: "/auth/api-keys/:id", description: "Revoke an API key" },
  ],
};

function ApiReferenceTab() {
  const origin = getOrigin();

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        All endpoints are prefixed with{" "}
        <code className="rounded bg-muted px-1.5 py-0.5 text-xs font-mono">
          {origin}/api/v1
        </code>
        . Authenticate with a Bearer token or X-API-Key header.
      </p>

      {Object.entries(API_ENDPOINTS).map(([category, endpoints]) => (
        <Card key={category}>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">{category}</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="divide-y">
              {endpoints.map((ep) => (
                <div
                  key={`${ep.method}-${ep.path}`}
                  className="flex items-start gap-3 py-2 first:pt-0 last:pb-0"
                >
                  <MethodBadge method={ep.method} />
                  <code className="text-xs font-mono shrink-0">{ep.path}</code>
                  <span className="text-xs text-muted-foreground ml-auto text-right">
                    {ep.description}
                  </span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      ))}

      <div className="flex justify-center pt-2">
        <Button
          variant="outline"
          onClick={() =>
            window.open(`${origin}/api/docs`, "_blank", "noopener")
          }
        >
          <ExternalLink className="mr-2 h-4 w-4" />
          Open Full Swagger Documentation
        </Button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab 3 — Code Snippets
// ---------------------------------------------------------------------------

function CodeSnippetsTab() {
  const origin = getOrigin();

  const curlSend = `# Send an email
curl -X POST ${origin}/api/v1/emails/send \\
  -H "Authorization: Bearer <token>" \\
  -H "Content-Type: application/json" \\
  -d '{
    "from": "sender@example.com",
    "to": ["recipient@example.com"],
    "subject": "Hello from MailCue",
    "body": "This is a test email.",
    "content_type": "text/plain"
  }'`;

  const curlInbox = `# List inbox emails
curl ${origin}/api/v1/emails?mailbox=user@example.com&folder=INBOX \\
  -H "Authorization: Bearer <token>"`;

  const curlInject = `# Inject a raw test email
curl -X POST ${origin}/api/v1/emails/inject \\
  -H "Authorization: Bearer <token>" \\
  -H "Content-Type: application/json" \\
  -d '{
    "mailbox": "user@example.com",
    "raw_message": "From: test@example.com\\r\\nTo: user@example.com\\r\\nSubject: Test\\r\\n\\r\\nHello!"
  }'`;

  const pythonExample = `import requests

BASE_URL = "${origin}/api/v1"
TOKEN = "<your-access-token>"
headers = {"Authorization": f"Bearer {TOKEN}"}

# Send an email
resp = requests.post(f"{BASE_URL}/emails/send", json={
    "from": "sender@example.com",
    "to": ["recipient@example.com"],
    "subject": "Hello from MailCue",
    "body": "This is a test email.",
    "content_type": "text/plain",
}, headers=headers)
print(resp.json())

# List inbox
resp = requests.get(f"{BASE_URL}/emails", params={
    "mailbox": "user@example.com",
    "folder": "INBOX",
}, headers=headers)
print(resp.json())`;

  const nodeExample = `const BASE_URL = "${origin}/api/v1";
const TOKEN = "<your-access-token>";

// Send an email
const sendRes = await fetch(\`\${BASE_URL}/emails/send\`, {
  method: "POST",
  headers: {
    "Authorization": \`Bearer \${TOKEN}\`,
    "Content-Type": "application/json",
  },
  body: JSON.stringify({
    from: "sender@example.com",
    to: ["recipient@example.com"],
    subject: "Hello from MailCue",
    body: "This is a test email.",
    content_type: "text/plain",
  }),
});
console.log(await sendRes.json());

// List inbox
const listRes = await fetch(
  \`\${BASE_URL}/emails?mailbox=user@example.com&folder=INBOX\`,
  { headers: { "Authorization": \`Bearer \${TOKEN}\` } },
);
console.log(await listRes.json());`;

  const goExample = `package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
)

const (
	baseURL = "${origin}/api/v1"
	token   = "<your-access-token>"
)

func main() {
	// Send an email
	payload, _ := json.Marshal(map[string]interface{}{
		"from":         "sender@example.com",
		"to":           []string{"recipient@example.com"},
		"subject":      "Hello from MailCue",
		"body":         "This is a test email.",
		"content_type": "text/plain",
	})

	req, _ := http.NewRequest("POST", baseURL+"/emails/send", bytes.NewReader(payload))
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("Content-Type", "application/json")

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		panic(err)
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)
	fmt.Println(string(body))
}`;

  return (
    <div className="space-y-6">
      <p className="text-sm text-muted-foreground">
        Ready-to-use code snippets for interacting with the MailCue API.
        Replace placeholder values with your actual credentials.
      </p>

      {/* curl */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center gap-2">
            <Terminal className="h-4 w-4" />
            curl
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <CodeBlock code={curlSend} language="bash" />
          <CodeBlock code={curlInbox} language="bash" />
          <CodeBlock code={curlInject} language="bash" />
        </CardContent>
      </Card>

      {/* Python */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Python</CardTitle>
          <CardDescription>Using the requests library</CardDescription>
        </CardHeader>
        <CardContent>
          <CodeBlock code={pythonExample} language="python" />
        </CardContent>
      </Card>

      {/* Node.js */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Node.js</CardTitle>
          <CardDescription>Using the built-in fetch API</CardDescription>
        </CardHeader>
        <CardContent>
          <CodeBlock code={nodeExample} language="javascript" />
        </CardContent>
      </Card>

      {/* Go */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Go</CardTitle>
          <CardDescription>Using net/http</CardDescription>
        </CardHeader>
        <CardContent>
          <CodeBlock code={goExample} language="go" />
        </CardContent>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab 4 — Environment
// ---------------------------------------------------------------------------

function EnvironmentTab() {
  const { data: settings, isLoading, isError } = useServerSettings();
  const host = getHost();
  const origin = getOrigin();

  return (
    <div className="grid gap-4 md:grid-cols-2">
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center gap-2">
            <Server className="h-4 w-4" />
            Server Information
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {isLoading ? (
            <div className="flex items-center gap-2 py-4">
              <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
              <span className="text-sm text-muted-foreground">Loading server settings...</span>
            </div>
          ) : isError ? (
            <p className="text-sm text-destructive">Failed to load server settings.</p>
          ) : (
            <>
              <div className="flex justify-between">
                <span className="text-sm text-muted-foreground">Hostname</span>
                <span className="text-sm font-mono">{settings?.hostname ?? host}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-sm text-muted-foreground">Domain</span>
                <span className="text-sm font-mono">{settings?.hostname ?? host}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-sm text-muted-foreground">Web UI</span>
                <span className="text-sm font-mono">{origin}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-sm text-muted-foreground">API Base</span>
                <span className="text-sm font-mono">{origin}/api/v1</span>
              </div>
            </>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center gap-2">
            <Check className="h-4 w-4" />
            Services
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-sm text-muted-foreground">SMTP</span>
            <Badge className="bg-emerald-600 text-white">Port 25 / 587</Badge>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-sm text-muted-foreground">IMAP</span>
            <Badge className="bg-emerald-600 text-white">Port 143 / 993</Badge>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-sm text-muted-foreground">POP3</span>
            <Badge className="bg-emerald-600 text-white">Port 110 / 995</Badge>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-sm text-muted-foreground">REST API</span>
            <Badge className="bg-emerald-600 text-white">Active</Badge>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-sm text-muted-foreground">SSE (Real-time)</span>
            <Badge className="bg-emerald-600 text-white">Active</Badge>
          </div>
        </CardContent>
      </Card>

      <Card className="md:col-span-2">
        <CardHeader className="pb-3">
          <CardTitle className="text-base">TLS Certificate</CardTitle>
          <CardDescription>
            Manage TLS certificates from the{" "}
            <a
              href="/settings?tab=certificate"
              className="text-primary underline underline-offset-4 hover:text-primary/80"
            >
              Settings page
            </a>
            .
          </CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            STARTTLS is required for SMTP submission on port 587. IMAP and POP3
            support both STARTTLS and dedicated SSL/TLS ports. Upload or generate
            certificates in Settings &gt; TLS Certificate.
          </p>
        </CardContent>
      </Card>

      <Card className="md:col-span-2">
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Docker Deployment</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            MailCue is designed to run as a Docker container. All data is persisted
            in a mounted volume. Ensure ports 25, 110, 143, 587, 993, 995, and
            your HTTP port are exposed in your Docker configuration. See the
            project README for the recommended{" "}
            <code className="rounded bg-muted px-1 py-0.5 text-xs font-mono">
              docker-compose.yml
            </code>{" "}
            setup.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page Root
// ---------------------------------------------------------------------------
// Integrations Tab
// ---------------------------------------------------------------------------

function IntegrationsTab() {
  const copy = useClipboard();
  const skillUrl = `${getOrigin()}/api/v1/integrations/openclaw/skill`;
  const curlCommand = `curl -o SKILL.md ${skillUrl}`;

  const handleDownload = () => {
    const link = document.createElement("a");
    link.href = skillUrl;
    link.download = "SKILL.md";
    link.click();
  };

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Bot className="h-5 w-5" />
            OpenClaw Skill
          </CardTitle>
          <CardDescription>
            Use MailCue with OpenClaw AI agent. The skill file is dynamically
            generated with your server URL and domain pre-configured.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap gap-2">
            <Button onClick={handleDownload} className="gap-2">
              <Download className="h-4 w-4" />
              Download SKILL.md
            </Button>
            <Button
              variant="outline"
              className="gap-2"
              onClick={() => copy(skillUrl, "Skill URL")}
            >
              <Copy className="h-4 w-4" />
              Copy URL
            </Button>
          </div>

          <div className="space-y-2">
            <p className="text-sm font-medium">Install via CLI</p>
            <CodeBlock code={curlCommand} language="bash" />
          </div>

          <div className="space-y-2">
            <p className="text-sm font-medium">What it supports</p>
            <div className="grid grid-cols-2 gap-1 text-sm text-muted-foreground">
              <span>Send, reply, forward emails</span>
              <span>Search and list emails</span>
              <span>Mark read/unread, delete</span>
              <span>Download attachments</span>
              <span>Manage mailboxes</span>
              <span>Manage aliases</span>
            </div>
          </div>

          <div className="space-y-2">
            <p className="text-sm font-medium">Required environment variable</p>
            <CopyField label="MAILCUE_API_KEY" value="mc_..." mono />
            <p className="text-xs text-muted-foreground">
              Create an API key from your{" "}
              <a href="/profile" className="underline">
                Profile page
              </a>
              .
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------

function DevToolsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const currentTab = searchParams.get("tab") ?? "connection";

  const handleTabChange = (value: string) => {
    setSearchParams({ tab: value }, { replace: true });
  };

  return (
    <div className="h-full overflow-auto p-6">
      <div className="mb-6">
        <h1 className="text-2xl font-bold">Developer Tools</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Connection details, API reference, code snippets, and server environment info.
        </p>
      </div>

      <Tabs value={currentTab} onValueChange={handleTabChange}>
        <TabsList className="mb-6">
          <TabsTrigger value="connection">
            <Plug className="mr-1.5 h-3.5 w-3.5" />
            Connection Info
          </TabsTrigger>
          <TabsTrigger value="api">
            <BookOpen className="mr-1.5 h-3.5 w-3.5" />
            API Reference
          </TabsTrigger>
          <TabsTrigger value="snippets">
            <Code2 className="mr-1.5 h-3.5 w-3.5" />
            Code Snippets
          </TabsTrigger>
          <TabsTrigger value="environment">
            <Server className="mr-1.5 h-3.5 w-3.5" />
            Environment
          </TabsTrigger>
          <TabsTrigger value="integrations">
            <Bot className="mr-1.5 h-3.5 w-3.5" />
            Integrations
          </TabsTrigger>
        </TabsList>

        <TabsContent value="connection">
          <ConnectionInfoTab />
        </TabsContent>

        <TabsContent value="api">
          <ApiReferenceTab />
        </TabsContent>

        <TabsContent value="snippets">
          <CodeSnippetsTab />
        </TabsContent>

        <TabsContent value="environment">
          <EnvironmentTab />
        </TabsContent>

        <TabsContent value="integrations">
          <IntegrationsTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}

export { DevToolsPage };
