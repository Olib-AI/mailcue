import { Send, Hash, MessagesSquare, Phone, MessageSquare, MessageCircle, Gamepad2 } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ProviderType } from "@/types/sandbox";

const PROVIDER_ICONS: Record<ProviderType, typeof MessageSquare> = {
  telegram: Send,
  slack: Hash,
  mattermost: MessagesSquare,
  twilio: Phone,
  whatsapp: MessageCircle,
  discord: Gamepad2,
  bandwidth: Phone,
  vonage: Phone,
  plivo: Phone,
  telnyx: Phone,
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
