import { EmailList } from "@/components/email/email-list";
import { EmailDetail } from "@/components/email/email-detail";
import { Separator } from "@/components/ui/separator";

function MailPage() {
  return (
    <div className="flex h-full">
      {/* Email List Panel */}
      <div className="w-80 min-w-[280px] max-w-[400px] flex-shrink-0 border-r flex flex-col overflow-hidden">
        <EmailList />
      </div>

      <Separator orientation="vertical" />

      {/* Email Detail Panel */}
      <div className="flex-1 overflow-hidden">
        <EmailDetail />
      </div>
    </div>
  );
}

export { MailPage };
