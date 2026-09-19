import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { AxiosAdapter } from "axios";
import { apiClient } from "./client";
import { useAuthStore } from "../store/authStore";

// axios has no public API to invoke a registered interceptor directly, so
// the standard way to observe what it does to a request is to swap in a
// fake adapter (the function axios ultimately calls to actually send the
// request) that just captures the fully-processed config -- interceptors
// run before the adapter, so this proves what they did without a real
// network call.
let capturedAuthHeader: unknown;
const captureAdapter: AxiosAdapter = async (config) => {
  capturedAuthHeader = config.headers?.Authorization;
  return {
    data: {},
    status: 200,
    statusText: "OK",
    headers: {},
    config,
  };
};

const originalAdapter = apiClient.defaults.adapter;

beforeEach(() => {
  capturedAuthHeader = undefined;
  apiClient.defaults.adapter = captureAdapter;
  useAuthStore.getState().logout();
});

afterEach(() => {
  apiClient.defaults.adapter = originalAdapter;
});

describe("apiClient auth interceptor", () => {
  it("attaches a Bearer Authorization header when a token is present", async () => {
    useAuthStore.getState().setAuth("tok123", "salt==", "user@example.com", {} as CryptoKey);
    await apiClient.get("/whatever");
    expect(capturedAuthHeader).toBe("Bearer tok123");
  });

  it("omits the Authorization header when logged out", async () => {
    await apiClient.get("/whatever");
    expect(capturedAuthHeader).toBeUndefined();
  });
});
