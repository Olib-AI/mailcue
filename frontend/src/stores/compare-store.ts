import { create } from "zustand";

interface CompareEmailRef {
  uid: string;
  mailbox: string;
  folder: string;
  subject: string;
  from_address: string;
}

interface CompareState {
  /** Emails selected for comparison, keyed by `${mailbox}:${uid}` */
  emails: Map<string, CompareEmailRef>;
  /** Whether the compare view dialog is open */
  compareViewOpen: boolean;

  addEmail: (ref: CompareEmailRef) => void;
  removeEmail: (mailbox: string, uid: string) => void;
  clearAll: () => void;
  hasEmail: (mailbox: string, uid: string) => boolean;
  setCompareViewOpen: (open: boolean) => void;
}

function makeKey(mailbox: string, uid: string): string {
  return `${mailbox}:${uid}`;
}

export const useCompareStore = create<CompareState>((set, get) => ({
  emails: new Map(),
  compareViewOpen: false,

  addEmail: (ref) =>
    set((state) => {
      const next = new Map(state.emails);
      next.set(makeKey(ref.mailbox, ref.uid), ref);
      return { emails: next };
    }),

  removeEmail: (mailbox, uid) =>
    set((state) => {
      const next = new Map(state.emails);
      next.delete(makeKey(mailbox, uid));
      return { emails: next };
    }),

  clearAll: () => set({ emails: new Map(), compareViewOpen: false }),

  hasEmail: (mailbox, uid) => get().emails.has(makeKey(mailbox, uid)),

  setCompareViewOpen: (open) => set({ compareViewOpen: open }),
}));

export type { CompareEmailRef };
