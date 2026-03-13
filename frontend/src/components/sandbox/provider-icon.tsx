import { Send, Hash, MessagesSquare, Phone, MessageSquare } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ProviderType } from "@/types/sandbox";

const PROVIDER_ICONS: Record<ProviderType, typeof MessageSquare> = {
  telegram: Send,
  slack: Hash,
  mattermost: MessagesSquare,
  twilio: Phone,
};

interface ProviderIconProps {
  type: ProviderType;
  className?: string;
}

function ProviderIcon({ type, className }: ProviderIconProps) {
  const Icon = PROVIDER_ICONS[type] ?? MessageSquare;
  return <Icon className={cn("h-4 w-4", className)} />;
}

export { ProviderIcon };
