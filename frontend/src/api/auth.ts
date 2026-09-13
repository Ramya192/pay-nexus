import { apiClient } from "./client";

export interface TokenResponse {
  access_token: string;
  token_type: string;
  encryption_salt: string; // base64 — see crypto/clientEncryption.ts
}

export async function register(email: string, password: string): Promise<TokenResponse> {
  const { data } = await apiClient.post<TokenResponse>("/auth/register", { email, password });
  return data;
}

export async function login(email: string, password: string): Promise<TokenResponse> {
  const { data } = await apiClient.post<TokenResponse>("/auth/login", { email, password });
  return data;
}
