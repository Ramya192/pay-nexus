import { create } from "zustand";

// Field shape matches backend/api/models/financial_profile.py's plaintext
// documentation exactly — no remapping needed at the API boundary.
export interface FinancialProfile {
  elssMutualFunds?: number;
  otherMutualFunds?: number;
  stocks?: number;
  fdPrincipal?: number;
  fdInterestEarned?: number;
  rdPrincipal?: number;
  rdInterestEarned?: number;
  homeLoanPrincipalPaid?: number;
  homeLoanInterestPaid?: number;
  lifeInsurancePremium?: number;
  healthInsurancePremium?: number;
  healthInsuranceForSeniorCitizen?: boolean;
}

interface FinancialProfileState {
  // Decrypted plaintext, same trust tier as payslipStore — session-only
  // until explicitly saved (encrypted) via FinancialProfileForm.
  profile: FinancialProfile | null;
  setProfile: (profile: FinancialProfile) => void;
  clear: () => void;
}

export const useFinancialProfileStore = create<FinancialProfileState>((set) => ({
  profile: null,
  setProfile: (profile) => set({ profile }),
  clear: () => set({ profile: null }),
}));
