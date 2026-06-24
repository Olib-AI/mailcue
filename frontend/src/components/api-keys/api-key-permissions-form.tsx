import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import type { ApiKeyScope, Mailbox } from "@/types/api";

export type AccessMode = "full" | "custom";

export interface ScopeGroup {
  group: string;
  scopes: ApiKeyScope[];
}

interface ApiKeyPermissionsFormProps {
  accessMode: AccessMode;
  onAccessModeChange: (mode: AccessMode) => void;
  scopeGroups: ScopeGroup[];
  selectedScopes: Set<string>;
  onToggleScope: (value: string) => void;
  restrictMailboxes: boolean;
  onRestrictMailboxesChange: (restrict: boolean) => void;
  mailboxes: Mailbox[];
  selectedMailboxes: Set<string>;
  onToggleMailbox: (address: string) => void;
}

const optionButtonClass = (active: boolean) =>
  cn(
    "rounded-md border p-3 text-left transition-colors",
    active ? "border-primary bg-primary/5" : "hover:border-primary/50"
  );

export function ApiKeyPermissionsForm({
  accessMode,
  onAccessModeChange,
  scopeGroups,
  selectedScopes,
  onToggleScope,
  restrictMailboxes,
  onRestrictMailboxesChange,
  mailboxes,
  selectedMailboxes,
  onToggleMailbox,
}: ApiKeyPermissionsFormProps) {
  const customWithNoScopes = accessMode === "custom" && selectedScopes.size === 0;

  return (
    <>
      <div className="space-y-2">
        <Label>Access</Label>
        <div className="grid gap-2 sm:grid-cols-2">
          <button
            type="button"
            onClick={() => onAccessModeChange("full")}
            className={optionButtonClass(accessMode === "full")}
          >
            <span className="text-sm font-medium">Full access</span>
            <p className="text-xs text-muted-foreground">
              Key can use every available scope.
            </p>
          </button>
          <button
            type="button"
            onClick={() => onAccessModeChange("custom")}
            className={optionButtonClass(accessMode === "custom")}
          >
            <span className="text-sm font-medium">Custom permissions</span>
            <p className="text-xs text-muted-foreground">
              Restrict the key to specific scopes.
            </p>
          </button>
        </div>
      </div>

      {accessMode === "custom" && (
        <div className="space-y-2">
          <Label>Permissions</Label>
          {scopeGroups.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Loading permissions...
            </p>
          ) : (
            <ScrollArea className="max-h-64 rounded-md border">
              <div className="space-y-4 p-3">
                {scopeGroups.map((group) => (
                  <div key={group.group} className="space-y-2">
                    <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                      {group.group}
                    </p>
                    <div className="space-y-2">
                      {group.scopes.map((scope) => (
                        <label
                          key={scope.value}
                          className="flex cursor-pointer items-start gap-2.5"
                        >
                          <Checkbox
                            checked={selectedScopes.has(scope.value)}
                            onCheckedChange={() => onToggleScope(scope.value)}
                            className="mt-0.5"
                          />
                          <span className="space-y-0.5">
                            <span className="block text-sm leading-none">
                              {scope.label}
                            </span>
                            <span className="block text-xs text-muted-foreground">
                              {scope.description}
                            </span>
                          </span>
                        </label>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </ScrollArea>
          )}
          {customWithNoScopes && (
            <p className="text-xs text-muted-foreground">
              Select at least one permission.
            </p>
          )}
        </div>
      )}

      <div className="space-y-2">
        <Label>Mailboxes</Label>
        <div className="grid gap-2 sm:grid-cols-2">
          <button
            type="button"
            onClick={() => onRestrictMailboxesChange(false)}
            className={optionButtonClass(!restrictMailboxes)}
          >
            <span className="text-sm font-medium">All my mailboxes</span>
          </button>
          <button
            type="button"
            onClick={() => onRestrictMailboxesChange(true)}
            className={optionButtonClass(restrictMailboxes)}
          >
            <span className="text-sm font-medium">
              Limit to specific mailboxes
            </span>
          </button>
        </div>
        {restrictMailboxes && (
          <ScrollArea className="max-h-40 rounded-md border">
            <div className="space-y-2 p-3">
              {mailboxes.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No mailboxes available.
                </p>
              ) : (
                mailboxes.map((mb) => (
                  <label
                    key={mb.id}
                    className="flex cursor-pointer items-center gap-2.5"
                  >
                    <Checkbox
                      checked={selectedMailboxes.has(mb.address)}
                      onCheckedChange={() => onToggleMailbox(mb.address)}
                    />
                    <span className="text-sm">{mb.address}</span>
                  </label>
                ))
              )}
            </div>
          </ScrollArea>
        )}
      </div>
    </>
  );
}
