import { useSearchParams } from "react-router-dom";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { MailboxManager } from "@/components/admin/mailbox-manager";
import { InjectForm } from "@/components/admin/inject-form";
import { GpgKeyManager } from "@/components/gpg/gpg-key-manager";

function AdminPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const currentTab = searchParams.get("tab") ?? "mailboxes";

  const handleTabChange = (value: string) => {
    setSearchParams({ tab: value }, { replace: true });
  };

  return (
    <div className="h-full overflow-auto p-6">
      <Tabs value={currentTab} onValueChange={handleTabChange}>
        <TabsList className="mb-6">
          <TabsTrigger value="mailboxes">Mailboxes</TabsTrigger>
          <TabsTrigger value="inject">Inject Email</TabsTrigger>
          <TabsTrigger value="gpg">GPG Keys</TabsTrigger>
        </TabsList>

        <TabsContent value="mailboxes">
          <MailboxManager />
        </TabsContent>

        <TabsContent value="inject">
          <InjectForm />
        </TabsContent>

        <TabsContent value="gpg">
          <GpgKeyManager />
        </TabsContent>
      </Tabs>
    </div>
  );
}

export { AdminPage };
