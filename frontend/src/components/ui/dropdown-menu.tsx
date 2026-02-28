import {
  createContext,
  useContext,
  useState,
  useRef,
  useEffect,
  useCallback,
  type ReactNode,
} from "react";
import { cn } from "@/lib/utils";

// --- Context ---

interface DropdownContextValue {
  open: boolean;
  setOpen: (open: boolean) => void;
  triggerRef: React.RefObject<HTMLButtonElement | null>;
}

const DropdownContext = createContext<DropdownContextValue | null>(null);

function useDropdown(): DropdownContextValue {
  const ctx = useContext(DropdownContext);
  if (!ctx)
    throw new Error("DropdownMenu components must be used within <DropdownMenu>");
  return ctx;
}

// --- Root ---

interface DropdownMenuProps {
  children: ReactNode;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}

function DropdownMenu({ children, open: controlledOpen, onOpenChange }: DropdownMenuProps) {
  const [internalOpen, setInternalOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const isControlled = controlledOpen !== undefined;
  const open = isControlled ? controlledOpen : internalOpen;

  const setOpen = useCallback(
    (next: boolean) => {
      if (!isControlled) setInternalOpen(next);
      onOpenChange?.(next);
    },
    [isControlled, onOpenChange]
  );

  return (
    <DropdownContext.Provider value={{ open, setOpen, triggerRef }}>
      <div className="relative inline-block">{children}</div>
    </DropdownContext.Provider>
  );
}

// --- Trigger ---

interface DropdownTriggerProps {
  children: ReactNode;
  className?: string;
  asChild?: boolean;
}

function DropdownMenuTrigger({ children, className }: DropdownTriggerProps) {
  const { open, setOpen, triggerRef } = useDropdown();

  return (
    <button
      ref={triggerRef}
      type="button"
      className={className}
      onClick={() => setOpen(!open)}
      aria-expanded={open}
      aria-haspopup="true"
    >
      {children}
    </button>
  );
}

// --- Content ---

interface DropdownContentProps {
  children: ReactNode;
  className?: string;
  align?: "start" | "center" | "end";
}

function DropdownMenuContent({
  children,
  className,
  align = "end",
}: DropdownContentProps) {
  const { open, setOpen } = useDropdown();
  const contentRef = useRef<HTMLDivElement>(null);

  // Close on outside click
  useEffect(() => {
    if (!open) return;

    const handleClick = (e: MouseEvent) => {
      if (
        contentRef.current &&
        !contentRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
      }
    };

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };

    document.addEventListener("mousedown", handleClick);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handleClick);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [open, setOpen]);

  if (!open) return null;

  return (
    <div
      ref={contentRef}
      role="menu"
      className={cn(
        "absolute z-50 min-w-[8rem] overflow-hidden rounded-md border bg-popover p-1 text-popover-foreground shadow-md",
        align === "end" && "right-0",
        align === "start" && "left-0",
        align === "center" && "left-1/2 -translate-x-1/2",
        "mt-1",
        className
      )}
    >
      {children}
    </div>
  );
}

// --- Item ---

interface DropdownItemProps {
  children: ReactNode;
  className?: string;
  onClick?: () => void;
  destructive?: boolean;
  disabled?: boolean;
}

function DropdownMenuItem({
  children,
  className,
  onClick,
  destructive,
  disabled,
}: DropdownItemProps) {
  const { setOpen } = useDropdown();

  return (
    <button
      type="button"
      role="menuitem"
      disabled={disabled}
      className={cn(
        "relative flex w-full cursor-default select-none items-center rounded-sm px-2 py-1.5 text-sm outline-none transition-colors hover:bg-accent hover:text-accent-foreground focus:bg-accent focus:text-accent-foreground",
        destructive && "text-destructive hover:text-destructive",
        disabled && "pointer-events-none opacity-50",
        className
      )}
      onClick={() => {
        onClick?.();
        setOpen(false);
      }}
    >
      {children}
    </button>
  );
}

// --- Label and Separator ---

function DropdownMenuLabel({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("px-2 py-1.5 text-sm font-semibold", className)}>
      {children}
    </div>
  );
}

function DropdownMenuSeparator({ className }: { className?: string }) {
  return <div className={cn("-mx-1 my-1 h-px bg-border", className)} />;
}

export {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
};
