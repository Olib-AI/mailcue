import { create } from "zustand";

interface SandboxState {
  selectedProviderId: string | null;
  setSelectedProviderId: (id: string | null) => void;
  selectedConversationId: string | null;
  setSelectedConversationId: (id: string | null) => void;
  inspectedMessageId: string | null;
  setInspectedMessageId: (id: string | null) => void;
  showRawJson: boolean;
  toggleRawJson: () => void;
  showWebhookLog: boolean;
  toggleWebhookLog: () => void;
}

export const useSandboxStore = create<SandboxState>((set) => ({
  selectedProviderId: null,
  setSelectedProviderId: (id) =>
    set({ selectedProviderId: id, selectedConversationId: null, inspectedMessageId: null }),
  selectedConversationId: null,
  setSelectedConversationId: (id) => set({ selectedConversationId: id }),
  inspectedMessageId: null,
  setInspectedMessageId: (id) => set({ inspectedMessageId: id }),
  showRawJson: false,
  toggleRawJson: () => set((state) => ({ showRawJson: !state.showRawJson })),
  showWebhookLog: false,
  toggleWebhookLog: () =>
    set((state) => ({ showWebhookLog: !state.showWebhookLog })),
}));
