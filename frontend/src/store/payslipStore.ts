import { create } from "zustand";

interface PayslipState {
  // The decrypted payslip for this session only — this is what /chat sends
  // as payslip_data (§4). Persisting it (POST /payslip/save) is a separate,
  // explicit action that encrypts it first; this store never does that itself.
  payslipData: Record<string, unknown> | null;
  setPayslipData: (data: Record<string, unknown>) => void;
  clear: () => void;
}

export const usePayslipStore = create<PayslipState>((set) => ({
  payslipData: null,
  setPayslipData: (data) => set({ payslipData: data }),
  clear: () => set({ payslipData: null }),
}));
