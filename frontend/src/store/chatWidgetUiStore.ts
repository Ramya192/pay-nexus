import { create } from "zustand";

/** ChatWidget's open/maximized state, lifted out of the component itself so
 * App.tsx can react to it too — specifically to reserve a right-hand margin
 * on <main> while the panel is open, so its ~520px floating width doesn't
 * sit on top of page content (a goal's Delete/"Update progress" buttons
 * were found fully hidden behind it on a standard 1280px viewport). Kept as
 * its own tiny store rather than local useState now that two components
 * need it, matching this codebase's convention (chatStore, budgetStore,
 * etc. are each their own file). */
interface ChatWidgetUiState {
  open: boolean;
  maximized: boolean;
  setOpen: (open: boolean) => void;
  setMaximized: (maximized: boolean) => void;
}

export const useChatWidgetUiStore = create<ChatWidgetUiState>((set) => ({
  // Defaults OPEN, not closed — see ChatWidget.tsx's docstring for why.
  open: true,
  maximized: false,
  setOpen: (open) => set({ open }),
  setMaximized: (maximized) => set({ maximized }),
}));
