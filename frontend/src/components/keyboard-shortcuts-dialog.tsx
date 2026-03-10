import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

const KBD_CLASSES =
  "inline-flex items-center rounded border border-border bg-muted px-1.5 py-0.5 text-xs font-mono font-medium";

interface ShortcutEntry {
  keys: string[];
  description: string;
}

interface ShortcutGroup {
  title: string;
  shortcuts: ShortcutEntry[];
}

const SHORTCUT_GROUPS: ShortcutGroup[] = [
  {
    title: "Navigation",
    shortcuts: [
      { keys: ["j", "\u2193"], description: "Select next email" },
      { keys: ["k", "\u2191"], description: "Select previous email" },
      { keys: ["Enter", "o"], description: "Open selected email" },
      { keys: ["/"], description: "Focus search" },
      { keys: ["Esc"], description: "Close dialog / deselect email" },
    ],
  },
  {
    title: "Actions",
    shortcuts: [
      { keys: ["c"], description: "Compose new email" },
      { keys: ["d", "Delete"], description: "Delete selected email" },
      { keys: ["?"], description: "Toggle this help" },
    ],
  },
  {
    title: "Go to...",
    shortcuts: [
      { keys: ["g", "i"], description: "Go to Inbox" },
      { keys: ["g", "s"], description: "Go to Sent" },
    ],
  },
];

interface KeyboardShortcutsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

function Kbd({ children }: { children: string }) {
  return <kbd className={KBD_CLASSES}>{children}</kbd>;
}

function KeyboardShortcutsDialog({
  open,
  onOpenChange,
}: KeyboardShortcutsDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[480px]">
        <DialogHeader>
          <DialogTitle>Keyboard Shortcuts</DialogTitle>
        </DialogHeader>

        <div className="space-y-5 mt-2">
          {SHORTCUT_GROUPS.map((group) => (
            <div key={group.title}>
              <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-2">
                {group.title}
              </h3>
              <div className="space-y-1.5">
                {group.shortcuts.map((shortcut) => (
                  <div
                    key={shortcut.description}
                    className="flex items-center justify-between py-1"
                  >
                    <span className="text-sm">{shortcut.description}</span>
                    <span className="flex items-center gap-1 shrink-0 ml-4">
                      {shortcut.keys.map((key, i) => (
                        <span key={key} className="flex items-center gap-1">
                          {i > 0 && group.title === "Go to..." ? (
                            <span className="text-xs text-muted-foreground">
                              then
                            </span>
                          ) : i > 0 ? (
                            <span className="text-xs text-muted-foreground">
                              /
                            </span>
                          ) : null}
                          <Kbd>{key}</Kbd>
                        </span>
                      ))}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}

export { KeyboardShortcutsDialog };
