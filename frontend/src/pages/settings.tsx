import { useSearchParams } from "react-router-dom";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { DomainManager } from "@/components/admin/domain-manager";
import { GpgKeyManager } from "@/components/gpg/gpg-key-manager";
import { CertificateManager } from "@/components/admin/certificate-manager";
import { MailServerManager } from "@/components/admin/mail-server";
import { ProductionStatusPanel } from "@/components/admin/production-status";
import { SignatureManager } from "@/components/admin/signature-manager";
import { useAuth } from "@/hooks/use-auth";

function SettingsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { user } = useAuth();
  const isAdmin = user?.is_admin ?? false;
  const currentTab = searchParams.get("tab") ?? "signatures";

  const handleTabChange = (value: string) => {
    setSearchParams({ tab: value }, { replace: true });
  };

  return (
    <div className="h-full overflow-auto p-6">
      <Tabs value={currentTab} onValueChange={handleTabChange}>
        <TabsList className="mb-6">
          <TabsTrigger value="signatures">Signatures</TabsTrigger>
          <TabsTrigger value="gpg">GPG Keys</TabsTrigger>
          {isAdmin && <TabsTrigger value="certificate">TLS Certificate</TabsTrigger>}
          {isAdmin && <TabsTrigger value="mail-server">Mail Server</TabsTrigger>}
          {isAdmin && <TabsTrigger value="domains">Domains</TabsTrigger>}
          {isAdmin && <TabsTrigger value="production">Production</TabsTrigger>}
        </TabsList>

        <TabsContent value="signatures">
          <SignatureManager />
        </TabsContent>

        <TabsContent value="gpg">
          <GpgKeyManager />
        </TabsContent>

        {isAdmin && (
          <TabsContent value="certificate">
            <CertificateManager />
          </TabsContent>
        )}

        {isAdmin && (
          <TabsContent value="mail-server">
            <MailServerManager />
          </TabsContent>
        )}

        {isAdmin && (
          <TabsContent value="domains">
            <DomainManager />
          </TabsContent>
        )}

        {isAdmin && (
          <TabsContent value="production">
            <ProductionStatusPanel />
          </TabsContent>
        )}
      </Tabs>
    </div>
  );
}

export { SettingsPage };
