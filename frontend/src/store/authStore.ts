import { create } from "zustand";

interface AuthState {
  token: string | null;
  encryptionSalt: string | null; // base64, as returned by POST /auth/register|login
  userEmail: string | null;
  // The derived AES-256-GCM key lives here — in memory, for this tab's
  // lifetime only. Deliberately not persisted to localStorage alongside the
  // token: a refresh re-deriving it from a re-entered password is the
  // trade-off for never having the key sit in storage (§4).
  aesKey: CryptoKey | null;
  setAuth: (token: string, encryptionSalt: string, userEmail: string, aesKey: CryptoKey) => void;
  logout: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  token: null,
  encryptionSalt: null,
  userEmail: null,
  aesKey: null,
  setAuth: (token, encryptionSalt, userEmail, aesKey) =>
    set({ token, encryptionSalt, userEmail, aesKey }),
  logout: () => set({ token: null, encryptionSalt: null, userEmail: null, aesKey: null }),
}));
