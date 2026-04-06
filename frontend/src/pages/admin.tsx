import { useSearchParams } from "react-router-dom";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { MailboxManager } from "@/components/admin/mailbox-manager";
import { InjectForm } from "@/components/admin/inject-form";
import { UserManager } from "@/components/admin/user-manager";
import { useAuth } from "@/hooks/use-auth";

function AdminPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const currentTab = searchParams.get("tab") ?? "mailboxes";
  const { user } = useAuth();
  const isAdmin = user?.is_admin ?? false;

  const handleTabChange = (value: string) => {
    setSearchParams({ tab: value }, { replace: true });
  };

  return (
    <div className="h-full overflow-auto p-6">
      <Tabs value={currentTab} onValueChange={handleTabChange}>
        <TabsList className="mb-6">
          <TabsTrigger value="mailboxes">Mailboxes</TabsTrigger>
          {isAdmin && <TabsTrigger value="users">Users</TabsTrigger>}
          {isAdmin && <TabsTrigger value="inject">Inject Email</TabsTrigger>}
        </TabsList>

        <TabsContent value="mailboxes">
          <MailboxManager />
        </TabsContent>

        {isAdmin && (
          <TabsContent value="users">
            <UserManager />
          </TabsContent>
        )}

        {isAdmin && (
          <TabsContent value="inject">
            <InjectForm />
          </TabsContent>
        )}
      </Tabs>
    </div>
  );
}

export { AdminPage };
