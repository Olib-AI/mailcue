import { useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { MailboxManager } from "@/components/admin/mailbox-manager";
import { InjectForm } from "@/components/admin/inject-form";
import { UserManager } from "@/components/admin/user-manager";
import { useAuth } from "@/hooks/use-auth";
import { useFeatures } from "@/hooks/use-features";

function AdminPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const currentTab = searchParams.get("tab") ?? "mailboxes";
  const { user } = useAuth();
  const isAdmin = user?.is_admin ?? false;
  const { features } = useFeatures();
  const showInject = isAdmin && features.inject;

  // If a user lands on ?tab=inject in production (e.g. via a stale
  // bookmark), bounce them back to the default tab.  Otherwise the
  // Tabs component would highlight a trigger that no longer exists.
  useEffect(() => {
    if (currentTab === "inject" && !showInject) {
      setSearchParams({}, { replace: true });
    }
  }, [currentTab, showInject, setSearchParams]);

  const handleTabChange = (value: string) => {
    setSearchParams({ tab: value }, { replace: true });
  };

  return (
    <div className="h-full overflow-auto p-6">
      <Tabs value={currentTab} onValueChange={handleTabChange}>
        <TabsList className="mb-6">
          <TabsTrigger value="mailboxes">Mailboxes</TabsTrigger>
          {isAdmin && <TabsTrigger value="users">Users</TabsTrigger>}
          {showInject && <TabsTrigger value="inject">Inject Email</TabsTrigger>}
        </TabsList>

        <TabsContent value="mailboxes">
          <MailboxManager />
        </TabsContent>

        {isAdmin && (
          <TabsContent value="users">
            <UserManager />
          </TabsContent>
        )}

        {showInject && (
          <TabsContent value="inject">
            <InjectForm />
          </TabsContent>
        )}
      </Tabs>
    </div>
  );
}

export { AdminPage };
