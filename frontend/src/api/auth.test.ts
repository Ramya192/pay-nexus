import { afterEach, describe, expect, it, vi } from "vitest";
import { apiClient } from "./client";
import { login, register } from "./auth";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("register", () => {
  it("posts credentials to /auth/register and returns the token response", async () => {
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({
      data: { access_token: "tok", token_type: "bearer", encryption_salt: "salt==" },
    });
    const result = await register("user@example.com", "hunter2");
    expect(post).toHaveBeenCalledWith("/auth/register", { email: "user@example.com", password: "hunter2" });
    expect(result).toEqual({ access_token: "tok", token_type: "bearer", encryption_salt: "salt==" });
  });
});

describe("login", () => {
  it("posts credentials to /auth/login and returns the token response", async () => {
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({
      data: { access_token: "tok", token_type: "bearer", encryption_salt: "salt==" },
    });
    const result = await login("user@example.com", "hunter2");
    expect(post).toHaveBeenCalledWith("/auth/login", { email: "user@example.com", password: "hunter2" });
    expect(result).toEqual({ access_token: "tok", token_type: "bearer", encryption_salt: "salt==" });
  });
});
