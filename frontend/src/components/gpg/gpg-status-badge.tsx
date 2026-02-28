import type { ReactNode } from "react";
import {
  ShieldCheck,
  ShieldX,
  ShieldAlert,
  Lock,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { GpgEmailInfo, SignatureStatus } from "@/types/api";

interface GpgStatusBadgeProps {
  gpg: GpgEmailInfo;
  compact?: boolean;
}

function getSignatureConfig(status: SignatureStatus | null): {
  icon: typeof ShieldCheck;
  label: string;
  className: string;
  title: string;
} {
  switch (status) {
    case "valid":
      return {
        icon: ShieldCheck,
        label: "Signed (valid)",
        className: "text-green-600",
        title: "Valid GPG signature",
      };
    case "invalid":
      return {
        icon: ShieldX,
        label: "Signed (invalid)",
        className: "text-red-600",
        title: "Invalid GPG signature",
      };
    case "expired_key":
      return {
        icon: ShieldAlert,
        label: "Signed (expired key)",
        className: "text-yellow-600",
        title: "GPG signature from expired key",
      };
    case "no_public_key":
      return {
        icon: ShieldAlert,
        label: "Signed (unknown key)",
        className: "text-yellow-600",
        title: "GPG signature from unknown key",
      };
    case "error":
      return {
        icon: ShieldX,
        label: "Signature error",
        className: "text-red-600",
        title: "Error verifying GPG signature",
      };
    default:
      return {
        icon: ShieldAlert,
        label: "Signed",
        className: "text-yellow-600",
        title: "GPG signed (status unknown)",
      };
  }
}

function GpgStatusBadge({ gpg, compact = false }: GpgStatusBadgeProps) {
  const badges: ReactNode[] = [];

  if (gpg.is_signed) {
    const config = getSignatureConfig(gpg.signature_status);
    const SignIcon = config.icon;

    if (compact) {
      badges.push(
        <span key="signed" title={config.title}>
          <SignIcon className={cn("h-3.5 w-3.5", config.className)} />
        </span>
      );
    } else {
      badges.push(
        <Badge
          key="signed"
          variant="outline"
          className={cn("gap-1", config.className)}
          title={config.title}
        >
          <SignIcon className="h-3 w-3" />
          {config.label}
        </Badge>
      );
    }
  }

  if (gpg.is_encrypted) {
    const encryptClassName = gpg.decrypted
      ? "text-green-600"
      : "text-yellow-600";
    const encryptLabel = gpg.decrypted ? "Encrypted (decrypted)" : "Encrypted";
    const encryptTitle = gpg.decrypted
      ? "Message was encrypted and successfully decrypted"
      : "Message is encrypted";

    if (compact) {
      badges.push(
        <span key="encrypted" title={encryptTitle}>
          <Lock className={cn("h-3.5 w-3.5", encryptClassName)} />
        </span>
      );
    } else {
      badges.push(
        <Badge
          key="encrypted"
          variant="outline"
          className={cn("gap-1", encryptClassName)}
          title={encryptTitle}
        >
          <Lock className="h-3 w-3" />
          {encryptLabel}
        </Badge>
      );
    }
  }

  if (badges.length === 0) return null;

  return <div className="flex items-center gap-1.5">{badges}</div>;
}

export { GpgStatusBadge };
