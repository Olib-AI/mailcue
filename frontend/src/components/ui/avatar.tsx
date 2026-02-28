import { cn } from "@/lib/utils";
import { getInitials } from "@/lib/utils";

interface AvatarProps {
  name: string;
  className?: string;
  size?: "sm" | "md" | "lg";
}

const sizeClasses = {
  sm: "h-7 w-7 text-xs",
  md: "h-9 w-9 text-sm",
  lg: "h-11 w-11 text-base",
} as const;

/**
 * Deterministic color from string — produces a stable hue for each unique name.
 */
function getAvatarColor(name: string): string {
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = name.charCodeAt(i) + ((hash << 5) - hash);
  }
  const hue = Math.abs(hash) % 360;
  return `oklch(0.65 0.15 ${hue})`;
}

function Avatar({ name, className, size = "md" }: AvatarProps) {
  const initials = getInitials(name);
  const bg = getAvatarColor(name);

  return (
    <div
      className={cn(
        "inline-flex items-center justify-center rounded-full font-medium text-white shrink-0",
        sizeClasses[size],
        className
      )}
      style={{ backgroundColor: bg }}
      aria-hidden="true"
    >
      {initials}
    </div>
  );
}

export { Avatar };
