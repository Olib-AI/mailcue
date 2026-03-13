import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { useSimulateMessage } from "@/hooks/use-sandbox";

interface SimulateDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  providerId: string;
}

function SimulateDialog({ open, onOpenChange, providerId }: SimulateDialogProps) {
  const [sender, setSender] = useState("");
  const [content, setContent] = useState("");
  const [contentType, setContentType] = useState("text");
  const [conversationName, setConversationName] = useState("");

  const simulate = useSimulateMessage();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();

    if (!sender.trim() || !content.trim()) {
      toast.error("Sender and content are required");
      return;
    }

    simulate.mutate(
      {
        providerId,
        data: {
          sender: sender.trim(),
          content: content.trim(),
          content_type: contentType,
          conversation_name: conversationName.trim() || undefined,
        },
      },
      {
        onSuccess: () => {
          toast.success("Message simulated successfully");
          setSender("");
          setContent("");
          setContentType("text");
          setConversationName("");
          onOpenChange(false);
        },
        onError: (error) => {
          toast.error("Failed to simulate message", {
            description: error.message,
          });
        },
      }
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Simulate Inbound Message</DialogTitle>
          <DialogDescription>
            Send a simulated inbound message to test your integration.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="sim-sender">Sender</Label>
            <Input
              id="sim-sender"
              placeholder="e.g. @johndoe or +15551234567"
              value={sender}
              onChange={(e) => setSender(e.target.value)}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="sim-content">Content</Label>
            <Textarea
              id="sim-content"
              placeholder="Message content..."
              rows={3}
              value={content}
              onChange={(e) => setContent(e.target.value)}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="sim-type">Content Type</Label>
            <Select
              id="sim-type"
              value={contentType}
              onChange={(e) => setContentType(e.target.value)}
            >
              <option value="text">Text</option>
              <option value="photo">Photo</option>
              <option value="document">Document</option>
            </Select>
          </div>

          <div className="space-y-2">
            <Label htmlFor="sim-convo">Conversation Name (optional)</Label>
            <Input
              id="sim-convo"
              placeholder="e.g. Support Chat"
              value={conversationName}
              onChange={(e) => setConversationName(e.target.value)}
            />
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={simulate.isPending}>
              {simulate.isPending ? "Sending..." : "Send Message"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export { SimulateDialog };
