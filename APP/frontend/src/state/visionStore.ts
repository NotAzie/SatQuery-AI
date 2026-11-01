import { create } from "zustand";

import type { ImageAsset } from "@/shared/types";

interface VisionStoreState {
  selectedAssets: ImageAsset[];
  panelOpen: boolean;
  setSelectedAssets: (assets: ImageAsset[]) => void;
  setPanelOpen: (open: boolean) => void;
}

export const useVisionStore = create<VisionStoreState>((set) => ({
  selectedAssets: [],
  panelOpen: false,
  setSelectedAssets: (selectedAssets) => set({ selectedAssets }),
  setPanelOpen: (panelOpen) => set({ panelOpen }),
}));
