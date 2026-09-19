import { beforeEach, describe, expect, it } from "vitest";
import { useAuthStore } from "./authStore";

const fakeKey = {} as CryptoKey;

beforeEach(() => {
  useAuthStore.getState().logout();
});

describe("useAuthStore", () => {
  it("starts logged out", () => {
    const s = useAuthStore.getState();
    expect(s.token).toBeNull();
    expect(s.encryptionSalt).toBeNull();
    expect(s.userEmail).toBeNull();
    expect(s.aesKey).toBeNull();
  });

  it("setAuth stores all four fields together", () => {
    useAuthStore.getState().setAuth("tok123", "salt==", "user@example.com", fakeKey);
    const s = useAuthStore.getState();
    expect(s.token).toBe("tok123");
    expect(s.encryptionSalt).toBe("salt==");
    expect(s.userEmail).toBe("user@example.com");
    expect(s.aesKey).toBe(fakeKey);
  });

  it("logout clears all four fields", () => {
    useAuthStore.getState().setAuth("tok123", "salt==", "user@example.com", fakeKey);
    useAuthStore.getState().logout();
    const s = useAuthStore.getState();
    expect(s.token).toBeNull();
    expect(s.encryptionSalt).toBeNull();
    expect(s.userEmail).toBeNull();
    expect(s.aesKey).toBeNull();
  });
});
