/**
 * Mirrors backend/categorization/categories.py's CATEGORIES — duplicated,
 * not imported (no shared package between this TS frontend and the Python
 * backend, same caveat as utils/alerts.ts). Used for the category-
 * correction dropdown in StatementList.tsx; both rules.py's keyword match
 * and the LLM fallback only ever produce a category from this same closed
 * set, so a user's manual correction should be constrained to it too — an
 * open text field would let a corrected category silently stop matching
 * BudgetPlanner's per-category targets. If the backend list ever changes,
 * update both.
 */
export const TRANSACTION_CATEGORIES = [
  "Income",
  "Rent",
  "Food & Dining",
  "Groceries",
  "Transport",
  "Subscriptions",
  "Shopping",
  "Utilities",
  "Uncategorized",
] as const;
