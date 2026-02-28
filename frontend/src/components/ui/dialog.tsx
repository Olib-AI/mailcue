import {
  createContext,
  useContext,
  useState,
  useCallback,
  useEffect,
  useRef,
  type ReactNode,
  type MouseEvent,
  type KeyboardEvent,
} from "react";
import { cn } from "@/lib/utils";
import { X } from "lucide-react";

// --- Context ---

interface DialogContextValue {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const DialogContext = createContext<DialogContextValue | null>(null);

function useDialogContext(): DialogContextValue {
  const ctx = useContext(DialogContext);
  if (!ctx) throw new Error("Dialog components must be used within <Dialog>");
  return ctx;
}

// --- Root ---

interface DialogProps {
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  children: ReactNode;
}

function Dialog({ open: controlledOpen, onOpenChange, children }: DialogProps) {
  const [internalOpen, setInternalOpen] = useState(false);
  const isControlled = controlledOpen !== undefined;
  const open = isControlled ? controlledOpen : internalOpen;

  const handleOpenChange = useCallback(
    (next: boolean) => {
      if (!isControlled) setInternalOpen(next);
      onOpenChange?.(next);
    },
    [isControlled, onOpenChange]
  );

  return (
    <DialogContext.Provider value={{ open, onOpenChange: handleOpenChange }}>
      {children}
    </DialogContext.Provider>
  );
}

// --- Trigger ---

interface DialogTriggerProps {
  children: ReactNode;
  asChild?: boolean;
  className?: string;
}

function DialogTrigger({ children, className }: DialogTriggerProps) {
  const { onOpenChange } = useDialogContext();
  return (
    <button
      type="button"
      className={className}
      onClick={() => onOpenChange(true)}
    >
      {children}
    </button>
  );
}

// --- Content ---

interface DialogContentProps {
  children: ReactNode;
  className?: string;
}

function DialogContent({ children, className }: DialogContentProps) {
  const { open, onOpenChange } = useDialogContext();
  const contentRef = useRef<HTMLDivElement>(null);

  // Trap focus and handle Escape
  useEffect(() => {
    if (!open) return;

    const handleKeyDown = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape") {
        onOpenChange(false);
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    document.body.style.overflow = "hidden";

    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = "";
    };
  }, [open, onOpenChange]);

  if (!open) return null;

  const handleBackdropClick = (e: MouseEvent) => {
    if (e.target === e.currentTarget) {
      onOpenChange(false);
    }
  };

  const handleBackdropKeyDown = (e: KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      onOpenChange(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/50 backdrop-blur-sm"
        onClick={handleBackdropClick}
        onKeyDown={handleBackdropKeyDown}
        role="button"
        tabIndex={-1}
        aria-label="Close dialog"
      />
      {/* Content */}
      <div
        ref={contentRef}
        role="dialog"
        aria-modal="true"
        className={cn(
          "relative z-50 grid w-full max-w-lg gap-4 border bg-background p-6 shadow-lg rounded-lg mx-4",
          "animate-in fade-in-0 zoom-in-95",
          className
        )}
      >
        {children}
        <button
          type="button"
          className="absolute right-4 top-4 rounded-sm opacity-70 transition-opacity hover:opacity-100 focus:outline-none focus:ring-2 focus:ring-ring"
          onClick={() => onOpenChange(false)}
          aria-label="Close"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}

// --- Header, Title, Description ---

interface DialogSectionProps {
  children: ReactNode;
  className?: string;
}

function DialogHeader({ children, className }: DialogSectionProps) {
  return (
    <div
      className={cn("flex flex-col space-y-1.5 text-center sm:text-left", className)}
    >
      {children}
    </div>
  );
}

function DialogTitle({ children, className }: DialogSectionProps) {
  return (
    <h2
      className={cn("text-lg font-semibold leading-none tracking-tight", className)}
    >
      {children}
    </h2>
  );
}

function DialogDescription({ children, className }: DialogSectionProps) {
  return (
    <p className={cn("text-sm text-muted-foreground", className)}>
      {children}
    </p>
  );
}

function DialogFooter({ children, className }: DialogSectionProps) {
  return (
    <div
      className={cn(
        "flex flex-col-reverse sm:flex-row sm:justify-end sm:space-x-2",
        className
      )}
    >
      {children}
    </div>
  );
}

export {
  Dialog,
  DialogTrigger,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
};
