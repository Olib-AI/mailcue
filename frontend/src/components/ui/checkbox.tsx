import { forwardRef, type InputHTMLAttributes } from "react";
import { Check, Minus } from "lucide-react";
import { cn } from "@/lib/utils";

interface CheckboxProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "type" | "checked" | "onChange"> {
  checked?: boolean | "indeterminate";
  onCheckedChange?: (checked: boolean) => void;
}

const Checkbox = forwardRef<HTMLButtonElement, CheckboxProps>(
  ({ className, checked = false, onCheckedChange, disabled, ...props }, ref) => {
    const isChecked = checked === true;
    const isIndeterminate = checked === "indeterminate";

    return (
      <button
        ref={ref}
        type="button"
        role="checkbox"
        aria-checked={isIndeterminate ? "mixed" : isChecked}
        disabled={disabled}
        className={cn(
          "peer h-4 w-4 shrink-0 rounded-sm border border-primary ring-offset-background",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
          "disabled:cursor-not-allowed disabled:opacity-50",
          "cursor-pointer transition-colors",
          (isChecked || isIndeterminate)
            ? "bg-primary text-primary-foreground border-primary"
            : "bg-background hover:border-primary/70",
          className
        )}
        {...(props as Record<string, unknown>)}
        onClick={(e) => {
          e.stopPropagation();
          onCheckedChange?.(!isChecked);
        }}
      >
        {isChecked && <Check className="h-3.5 w-3.5" />}
        {isIndeterminate && <Minus className="h-3.5 w-3.5" />}
      </button>
    );
  }
);
Checkbox.displayName = "Checkbox";

export { Checkbox };
