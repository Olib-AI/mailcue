import { useEffect } from "react";
import { useSearchParams } from "react-router";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { MailboxManager } from "@/components/admin/mailbox-manager";
import { InjectForm } from "@/components/admin/inject-form";
import { UserManager } from "@/components/admin/user-manager";
import { WarmupManager } from "@/components/admin/warmup-manager";
import { useAuth } from "@/hooks/use-auth";
import { useFeatures } from "@/hooks/use-features";

function AdminPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const currentTab = searchParams.get("tab") ?? "mailboxes";
  const { user } = useAuth();
  const isAdmin = user?.is_admin ?? false;
  const { features } = useFeatures();
  const showInject = isAdmin && features.inject;

  // Bounce stale or unauthorized tab URLs back to the default tab.
  useEffect(() => {
    if (
      (currentTab === "inject" && !showInject) ||
      (!isAdmin && (currentTab === "users" || currentTab === "warmup"))
    ) {
      setSearchParams({}, { replace: true });
    }
  }, [currentTab, isAdmin, showInject, setSearchParams]);

  const handleTabChange = (value: string) => {
    setSearchParams({ tab: value }, { replace: true });
  };

  return (
    <div className="h-full overflow-auto p-6">
      <Tabs value={currentTab} onValueChange={handleTabChange}>
        <TabsList className="mb-6">
          <TabsTrigger value="mailboxes">Mailboxes</TabsTrigger>
          {isAdmin && <TabsTrigger value="users">Users</TabsTrigger>}
          {isAdmin && <TabsTrigger value="warmup">Email Warmup</TabsTrigger>}
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

        {isAdmin && (
          <TabsContent value="warmup">
            <WarmupManager />
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
