import {
  createContext,
  useContext,
  useState,
  type ReactNode,
} from "react";
import { cn } from "@/lib/utils";

// --- Context ---

interface TabsContextValue {
  value: string;
  onValueChange: (value: string) => void;
}

const TabsContext = createContext<TabsContextValue | null>(null);

function useTabsContext(): TabsContextValue {
  const ctx = useContext(TabsContext);
  if (!ctx) throw new Error("Tabs components must be used within <Tabs>");
  return ctx;
}

// --- Root ---

interface TabsProps {
  value?: string;
  defaultValue?: string;
  onValueChange?: (value: string) => void;
  children: ReactNode;
  className?: string;
}

function Tabs({
  value: controlledValue,
  defaultValue = "",
  onValueChange,
  children,
  className,
}: TabsProps) {
  const [internalValue, setInternalValue] = useState(defaultValue);
  const isControlled = controlledValue !== undefined;
  const value = isControlled ? controlledValue : internalValue;

  const handleChange = (next: string) => {
    if (!isControlled) setInternalValue(next);
    onValueChange?.(next);
  };

  return (
    <TabsContext.Provider value={{ value, onValueChange: handleChange }}>
      <div className={className}>{children}</div>
    </TabsContext.Provider>
  );
}

// --- List ---

interface TabsListProps {
  children: ReactNode;
  className?: string;
}

function TabsList({ children, className }: TabsListProps) {
  return (
    <div
      role="tablist"
      className={cn(
        "inline-flex h-9 items-center justify-center rounded-lg bg-muted p-1 text-muted-foreground",
        className
      )}
    >
      {children}
    </div>
  );
}

// --- Trigger ---

interface TabsTriggerProps {
  value: string;
  children: ReactNode;
  className?: string;
  disabled?: boolean;
}

function TabsTrigger({
  value,
  children,
  className,
  disabled,
}: TabsTriggerProps) {
  const { value: selected, onValueChange } = useTabsContext();
  const isSelected = selected === value;

  return (
    <button
      type="button"
      role="tab"
      aria-selected={isSelected}
      disabled={disabled}
      className={cn(
        "inline-flex items-center justify-center whitespace-nowrap rounded-md px-3 py-1 text-sm font-medium ring-offset-background transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50",
        isSelected
          ? "bg-background text-foreground shadow"
          : "hover:bg-background/50 hover:text-foreground",
        className
      )}
      onClick={() => onValueChange(value)}
    >
      {children}
    </button>
  );
}

// --- Content ---

interface TabsContentProps {
  value: string;
  children: ReactNode;
  className?: string;
}

function TabsContent({ value, children, className }: TabsContentProps) {
  const { value: selected } = useTabsContext();

  if (selected !== value) return null;

  return (
    <div
      role="tabpanel"
      className={cn(
        "mt-2 ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
        className
      )}
    >
      {children}
    </div>
  );
}

export { Tabs, TabsList, TabsTrigger, TabsContent };
