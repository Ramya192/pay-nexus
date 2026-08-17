import { create } from "zustand";

// Matches backend/categorization/categories.py's CATEGORIES minus "Income"
// and "Uncategorized" — a budget targets spending categories, not those
// two (same exclusion backend/budgeting/budgets.py's DEFAULT_MONTHLY_BUDGETS
// makes). Also matches backend/budgeting/budgets.py's DEFAULT_MONTHLY_BUDGETS
// key set exactly.
export const BUDGET_CATEGORIES = [
  "Rent",
  "Food & Dining",
  "Groceries",
  "Transport",
  "Subscriptions",
  "Shopping",
  "Utilities",
] as const;

// {category: monthly amount} — keys match BUDGET_CATEGORIES above.
export type Budget = Record<string, number>;

interface BudgetState {
  // Decrypted plaintext, same trust tier as financialProfileStore's
  // profile — session-only until explicitly saved (encrypted) via
  // BudgetForm.tsx.
  budget: Budget | null;
  setBudget: (budget: Budget) => void;
  clear: () => void;
}

export const useBudgetStore = create<BudgetState>((set) => ({
  budget: null,
  setBudget: (budget) => set({ budget }),
  clear: () => set({ budget: null }),
}));
