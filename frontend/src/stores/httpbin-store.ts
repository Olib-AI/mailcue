import { create } from "zustand";

interface HttpBinState {
  selectedBinId: string | null;
  setSelectedBinId: (id: string | null) => void;
  selectedRequestId: string | null;
  setSelectedRequestId: (id: string | null) => void;
}

export const useHttpBinStore = create<HttpBinState>((set) => ({
  selectedBinId: null,
  setSelectedBinId: (id) => set({ selectedBinId: id, selectedRequestId: null }),
  selectedRequestId: null,
  setSelectedRequestId: (id) => set({ selectedRequestId: id }),
}));
