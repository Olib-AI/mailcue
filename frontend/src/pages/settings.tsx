import { useSearchParams } from "react-router-dom";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { DomainManager } from "@/components/admin/domain-manager";
import { GpgKeyManager } from "@/components/gpg/gpg-key-manager";
import { CertificateManager } from "@/components/admin/certificate-manager";
import { MailServerManager } from "@/components/admin/mail-server";
import { ProductionStatusPanel } from "@/components/admin/production-status";

function SettingsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const currentTab = searchParams.get("tab") ?? "gpg";

  const handleTabChange = (value: string) => {
    setSearchParams({ tab: value }, { replace: true });
  };

  return (
    <div className="h-full overflow-auto p-6">
      <Tabs value={currentTab} onValueChange={handleTabChange}>
        <TabsList className="mb-6">
          <TabsTrigger value="gpg">GPG Keys</TabsTrigger>
          <TabsTrigger value="certificate">TLS Certificate</TabsTrigger>
          <TabsTrigger value="mail-server">Mail Server</TabsTrigger>
          <TabsTrigger value="domains">Domains</TabsTrigger>
          <TabsTrigger value="production">Production</TabsTrigger>
        </TabsList>

        <TabsContent value="gpg">
          <GpgKeyManager />
        </TabsContent>

        <TabsContent value="certificate">
          <CertificateManager />
        </TabsContent>

        <TabsContent value="mail-server">
          <MailServerManager />
        </TabsContent>

        <TabsContent value="domains">
          <DomainManager />
        </TabsContent>

        <TabsContent value="production">
          <ProductionStatusPanel />
        </TabsContent>
      </Tabs>
    </div>
  );
}

export { SettingsPage };
