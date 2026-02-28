import { cn } from "@/lib/utils";

interface SeparatorProps {
  className?: string;
  orientation?: "horizontal" | "vertical";
}

function Separator({
  className,
  orientation = "horizontal",
}: SeparatorProps) {
  return (
    <div
      role="separator"
      aria-orientation={orientation}
      className={cn(
        "shrink-0 bg-border",
        orientation === "horizontal" ? "h-[1px] w-full" : "h-full w-[1px]",
        className
      )}
    />
  );
}

export { Separator };
