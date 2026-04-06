import { useState, useCallback } from "react";
import { useForm, Controller } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import {
  Plus,
  Loader2,
  AlertCircle,
  RefreshCw,
  Users,
  Pencil,
  UserX,
  Shield,
  ShieldCheck,
  KeyRound,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from "@/components/ui/dialog";
import {
  useUsers,
  useCreateUser,
  useUpdateUser,
} from "@/hooks/use-users";
import { useAuth } from "@/hooks/use-auth";
import type { User } from "@/types/api";
import { formatEmailDate } from "@/lib/utils";

const createUserSchema = z.object({
  username: z
    .string()
    .min(1, "Username is required")
    .regex(
      /^[a-zA-Z0-9._-]+$/,
      "Username can only contain letters, numbers, dots, hyphens, and underscores"
    ),
  email: z.string().min(1, "Email is required").email("Invalid email address"),
  password: z.string().min(8, "Password must be at least 8 characters"),
  is_admin: z.boolean(),
  max_mailboxes: z.coerce.number().int().min(1, "Must be at least 1"),
});

type CreateUserValues = z.infer<typeof createUserSchema>;

const editUserSchema = z.object({
  max_mailboxes: z.coerce.number().int().min(1, "Must be at least 1"),
  is_admin: z.boolean(),
  is_active: z.boolean(),
});

type EditUserValues = z.infer<typeof editUserSchema>;

function UserManager() {
  const { data, isLoading, isError, error, refetch } = useUsers();
  const createUser = useCreateUser();
  const updateUser = useUpdateUser();
  const currentUser = useAuth((s) => s.user);

  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<User | null>(null);
  const [deactivateTarget, setDeactivateTarget] = useState<User | null>(null);

  const createForm = useForm<CreateUserValues>({
    resolver: zodResolver(createUserSchema),
    defaultValues: {
      username: "",
      email: "",
      password: "",
      is_admin: false,
      max_mailboxes: 5,
    },
  });

  const editForm = useForm<EditUserValues>({
    resolver: zodResolver(editUserSchema),
  });

  const openEditDialog = useCallback(
    (user: User) => {
      editForm.reset({
        max_mailboxes: user.max_mailboxes,
        is_admin: user.is_admin,
        is_active: user.is_active,
      });
      setEditTarget(user);
    },
    [editForm]
  );

  const onCreateSubmit = (values: CreateUserValues) => {
    createUser.mutate(
      {
        username: values.username,
        email: values.email,
        password: values.password,
        is_admin: values.is_admin || undefined,
        max_mailboxes: values.max_mailboxes,
      },
      {
        onSuccess: (result) => {
          toast.success(`User created: ${result.username}`);
          createForm.reset();
          setCreateDialogOpen(false);
        },
        onError: (err) => {
          toast.error(
            err instanceof Error ? err.message : "Failed to create user"
          );
        },
      }
    );
  };

  const onEditSubmit = (values: EditUserValues) => {
    if (!editTarget) return;
    updateUser.mutate(
      {
        userId: editTarget.id,
        data: {
          max_mailboxes: values.max_mailboxes,
          is_admin: values.is_admin,
          is_active: values.is_active,
        },
      },
      {
        onSuccess: () => {
          toast.success(`User updated: ${editTarget.username}`);
          setEditTarget(null);
        },
        onError: (err) => {
          toast.error(
            err instanceof Error ? err.message : "Failed to update user"
          );
        },
      }
    );
  };

  const handleDeactivate = useCallback(() => {
    if (!deactivateTarget) return;
    updateUser.mutate(
      {
        userId: deactivateTarget.id,
        data: { is_active: false },
      },
      {
        onSuccess: () => {
          toast.success(`User deactivated: ${deactivateTarget.username}`);
          setDeactivateTarget(null);
        },
        onError: (err) => {
          toast.error(
            err instanceof Error ? err.message : "Failed to deactivate user"
          );
        },
      }
    );
  }, [deactivateTarget, updateUser]);

  const users = data?.users ?? [];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold tracking-tight">Users</h2>
          <p className="text-sm text-muted-foreground">
            Manage user accounts and permissions
          </p>
        </div>
        <Button onClick={() => setCreateDialogOpen(true)}>
          <Plus className="mr-2 h-4 w-4" />
          Create User
        </Button>
      </div>

      {/* User List */}
      {isLoading ? (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 3 }, (_, i) => (
            <Card key={i}>
              <CardHeader>
                <Skeleton className="h-5 w-40" />
              </CardHeader>
              <CardContent>
                <div className="space-y-2">
                  <Skeleton className="h-4 w-24" />
                  <Skeleton className="h-4 w-32" />
                  <Skeleton className="h-4 w-20" />
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      ) : isError ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-8">
            <AlertCircle className="h-10 w-10 text-destructive mb-3" />
            <p className="text-sm text-destructive mb-3">
              {error instanceof Error
                ? error.message
                : "Failed to load users"}
            </p>
            <Button
              variant="outline"
              size="sm"
              onClick={() => void refetch()}
            >
              <RefreshCw className="mr-2 h-4 w-4" />
              Retry
            </Button>
          </CardContent>
        </Card>
      ) : users.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-12">
            <Users className="h-12 w-12 text-muted-foreground/50 mb-3" />
            <p className="text-sm font-medium text-muted-foreground">
              No users yet
            </p>
            <p className="text-xs text-muted-foreground mt-1">
              Create your first user to get started
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {users.map((user) => (
            <Card key={user.id}>
              <CardHeader className="pb-3">
                <CardTitle className="text-base flex items-center justify-between">
                  <span className="truncate">{user.username}</span>
                  <div className="flex items-center gap-0.5 shrink-0">
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7 text-muted-foreground hover:text-primary"
                      onClick={() => openEditDialog(user)}
                      aria-label={`Edit ${user.username}`}
                      title="Edit user"
                    >
                      <Pencil className="h-4 w-4" />
                    </Button>
                    {currentUser?.id !== user.id && user.is_active && (
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7 text-muted-foreground hover:text-destructive"
                        onClick={() => setDeactivateTarget(user)}
                        aria-label={`Deactivate ${user.username}`}
                        title="Deactivate user"
                      >
                        <UserX className="h-4 w-4" />
                      </Button>
                    )}
                  </div>
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-2">
                  <p className="text-sm text-muted-foreground truncate">
                    {user.email}
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    <Badge variant={user.is_admin ? "default" : "secondary"}>
                      {user.is_admin ? (
                        <ShieldCheck className="mr-1 h-3 w-3" />
                      ) : (
                        <Shield className="mr-1 h-3 w-3" />
                      )}
                      {user.is_admin ? "Admin" : "User"}
                    </Badge>
                    <Badge
                      variant={user.is_active ? "secondary" : "destructive"}
                    >
                      {user.is_active ? "Active" : "Inactive"}
                    </Badge>
                    {user.totp_enabled && (
                      <Badge variant="outline">
                        <KeyRound className="mr-1 h-3 w-3" />
                        2FA
                      </Badge>
                    )}
                  </div>
                  <div className="space-y-1 text-sm text-muted-foreground pt-1">
                    <div className="flex justify-between">
                      <span>Max Mailboxes</span>
                      <span className="font-medium text-foreground">
                        {user.max_mailboxes}
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span>Created</span>
                      <span>{formatEmailDate(user.created_at)}</span>
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Create User Dialog */}
      <Dialog open={createDialogOpen} onOpenChange={setCreateDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create User</DialogTitle>
            <DialogDescription>
              Create a new user account. They will be able to log in and manage
              their own mailboxes.
            </DialogDescription>
          </DialogHeader>

          <form
            onSubmit={createForm.handleSubmit(onCreateSubmit)}
            className="space-y-4"
          >
            <div className="space-y-1.5">
              <Label htmlFor="user-username">Username</Label>
              <Input
                id="user-username"
                placeholder="johndoe"
                autoFocus
                {...createForm.register("username")}
              />
              {createForm.formState.errors.username && (
                <p className="text-xs text-destructive">
                  {createForm.formState.errors.username.message}
                </p>
              )}
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="user-email">Email</Label>
              <Input
                id="user-email"
                type="email"
                placeholder="john@example.com"
                {...createForm.register("email")}
              />
              {createForm.formState.errors.email && (
                <p className="text-xs text-destructive">
                  {createForm.formState.errors.email.message}
                </p>
              )}
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="user-password">Password</Label>
              <Input
                id="user-password"
                type="password"
                placeholder="Minimum 8 characters"
                {...createForm.register("password")}
              />
              {createForm.formState.errors.password && (
                <p className="text-xs text-destructive">
                  {createForm.formState.errors.password.message}
                </p>
              )}
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="user-max-mailboxes">Max Mailboxes</Label>
              <Input
                id="user-max-mailboxes"
                type="number"
                min={1}
                {...createForm.register("max_mailboxes")}
              />
              {createForm.formState.errors.max_mailboxes && (
                <p className="text-xs text-destructive">
                  {createForm.formState.errors.max_mailboxes.message}
                </p>
              )}
            </div>

            <div className="flex items-center gap-2">
              <Controller
                control={createForm.control}
                name="is_admin"
                render={({ field }) => (
                  <Checkbox
                    id="user-is-admin"
                    checked={field.value}
                    onCheckedChange={field.onChange}
                  />
                )}
              />
              <Label htmlFor="user-is-admin" className="cursor-pointer">
                Administrator
              </Label>
            </div>

            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  createForm.reset();
                  setCreateDialogOpen(false);
                }}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={createUser.isPending}>
                {createUser.isPending && (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                )}
                Create User
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* Edit User Dialog */}
      <Dialog
        open={editTarget !== null}
        onOpenChange={(open) => {
          if (!open) setEditTarget(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Edit User</DialogTitle>
            <DialogDescription>
              Update settings for <strong>{editTarget?.username}</strong>.
            </DialogDescription>
          </DialogHeader>

          <form
            onSubmit={editForm.handleSubmit(onEditSubmit)}
            className="space-y-4"
          >
            <div className="space-y-1.5">
              <Label htmlFor="edit-max-mailboxes">Max Mailboxes</Label>
              <Input
                id="edit-max-mailboxes"
                type="number"
                min={1}
                {...editForm.register("max_mailboxes")}
              />
              {editForm.formState.errors.max_mailboxes && (
                <p className="text-xs text-destructive">
                  {editForm.formState.errors.max_mailboxes.message}
                </p>
              )}
            </div>

            <div className="flex items-center gap-2">
              <Controller
                control={editForm.control}
                name="is_admin"
                render={({ field }) => (
                  <Checkbox
                    id="edit-is-admin"
                    checked={field.value}
                    onCheckedChange={field.onChange}
                  />
                )}
              />
              <Label htmlFor="edit-is-admin" className="cursor-pointer">
                Administrator
              </Label>
            </div>

            <div className="flex items-center gap-2">
              <Controller
                control={editForm.control}
                name="is_active"
                render={({ field }) => (
                  <Checkbox
                    id="edit-is-active"
                    checked={field.value}
                    onCheckedChange={field.onChange}
                  />
                )}
              />
              <Label htmlFor="edit-is-active" className="cursor-pointer">
                Active
              </Label>
            </div>

            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => setEditTarget(null)}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={updateUser.isPending}>
                {updateUser.isPending && (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                )}
                Save Changes
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* Deactivate Confirmation Dialog */}
      <Dialog
        open={deactivateTarget !== null}
        onOpenChange={(open) => {
          if (!open) setDeactivateTarget(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Deactivate User</DialogTitle>
            <DialogDescription>
              Are you sure you want to deactivate{" "}
              <strong>{deactivateTarget?.username}</strong>? They will no longer
              be able to log in. You can reactivate them later.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setDeactivateTarget(null)}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={handleDeactivate}
              disabled={updateUser.isPending}
            >
              {updateUser.isPending && (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              )}
              Deactivate
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

export { UserManager };
