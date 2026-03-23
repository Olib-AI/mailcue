import { ArrowLeft } from "lucide-react";
import { EmailList } from "@/components/email/email-list";
import { EmailDetail } from "@/components/email/email-detail";
import { Separator } from "@/components/ui/separator";
import { Button } from "@/components/ui/button";
import { useUIStore } from "@/stores/ui-store";

function MailPage() {
  const { selectedEmailUid, setSelectedEmailUid } = useUIStore();
  const hasSelection = selectedEmailUid !== null;

  return (
    <div className="flex h-full">
      {/* Email List Panel — hidden on mobile when an email is selected */}
      <div
        className={`w-full md:w-80 md:min-w-[280px] md:max-w-[400px] flex-shrink-0 border-r flex flex-col overflow-hidden ${
          hasSelection ? "hidden md:flex" : "flex"
        }`}
      >
        <EmailList />
      </div>

      <Separator orientation="vertical" className="hidden md:block" />

      {/* Email Detail Panel — hidden on mobile when no email is selected */}
      <div
        className={`flex-1 overflow-hidden flex-col ${
          hasSelection ? "flex" : "hidden md:flex"
        }`}
      >
        {/* Mobile back button */}
        {hasSelection && (
          <div className="flex items-center border-b px-2 py-1.5 md:hidden">
            <Button
              variant="ghost"
              size="sm"
              className="gap-1.5"
              onClick={() => setSelectedEmailUid(null)}
            >
              <ArrowLeft className="h-4 w-4" />
              Back
            </Button>
          </div>
        )}
        <div className="flex-1 overflow-hidden">
          <EmailDetail />
        </div>
      </div>
    </div>
  );
}

export { MailPage };
