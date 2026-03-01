import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useEffect, useRef, useState } from "react";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { setupTotp, confirmTotp } from "@/lib/auth";
import type { TOTPSetupResponse } from "@/types/api";

const codeSchema = z.object({
  code: z
    .string()
    .min(6, "Enter a 6-digit code")
    .max(6, "Enter a 6-digit code")
    .regex(/^\d{6}$/, "Code must be 6 digits"),
});

type CodeFormValues = z.infer<typeof codeSchema>;

interface TOTPSetupDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSuccess: () => void;
}

function TOTPSetupDialog({
  open,
  onOpenChange,
  onSuccess,
}: TOTPSetupDialogProps) {
  const [loading, setLoading] = useState(false);
  const [setupData, setSetupData] = useState<TOTPSetupResponse | null>(null);
  const fetchedRef = useRef(false);

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<CodeFormValues>({
    resolver: zodResolver(codeSchema),
    defaultValues: { code: "" },
  });

  // Fetch TOTP setup data when the dialog opens.
  useEffect(() => {
    if (open && !setupData && !fetchedRef.current) {
      fetchedRef.current = true;
      setLoading(true);
      setupTotp()
        .then((data) => setSetupData(data))
        .catch((err) => {
          toast.error(
            err instanceof Error ? err.message : "Failed to setup TOTP"
          );
          onOpenChange(false);
        })
        .finally(() => setLoading(false));
    }
    if (!open) {
      setSetupData(null);
      fetchedRef.current = false;
      reset();
    }
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  const onSubmit = async (data: CodeFormValues) => {
    setLoading(true);
    try {
      await confirmTotp(data.code);
      toast.success("Two-factor authentication enabled");
      setSetupData(null);
      reset();
      onOpenChange(false);
      onSuccess();
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Invalid code. Please try again."
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Set Up Two-Factor Authentication</DialogTitle>
          <DialogDescription>
            Scan the QR code with your authenticator app, then enter the
            verification code.
          </DialogDescription>
        </DialogHeader>

        {loading && !setupData ? (
          <div className="flex justify-center py-8">
            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
          </div>
        ) : setupData ? (
          <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
            {/* QR Code */}
            <div className="flex justify-center">
              <img
                src={setupData.qr_code}
                alt="TOTP QR Code"
                className="h-48 w-48 rounded-lg border"
              />
            </div>

            {/* Manual entry key */}
            <div className="space-y-1.5">
              <Label>Manual Entry Key</Label>
              <div className="rounded-md bg-muted p-2 text-center font-mono text-sm select-all break-all">
                {setupData.secret}
              </div>
            </div>

            {/* Verification code */}
            <div className="space-y-1.5">
              <Label htmlFor="totp-verify-code">Verification Code</Label>
              <Input
                id="totp-verify-code"
                type="text"
                inputMode="numeric"
                autoComplete="one-time-code"
                placeholder="000000"
                maxLength={6}
                className="text-center text-lg tracking-widest"
                {...register("code")}
              />
              {errors.code && (
                <p className="text-xs text-destructive">
                  {errors.code.message}
                </p>
              )}
            </div>

            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => onOpenChange(false)}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={loading}>
                {loading && (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                )}
                Enable 2FA
              </Button>
            </DialogFooter>
          </form>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

export { TOTPSetupDialog };
