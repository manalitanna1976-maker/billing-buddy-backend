import { apiClient } from "./client";

interface TokenResponse {
  access_token: string;
  token_type: string;
}

export async function signup(body: {
  business_name: string;
  email: string;
  password: string;
}): Promise<TokenResponse> {
  const { data } = await apiClient.post<TokenResponse>("/auth/signup", body);
  return data;
}

export async function login(body: { email: string; password: string }): Promise<TokenResponse> {
  const { data } = await apiClient.post<TokenResponse>("/auth/login", body);
  return data;
}

export async function logout(): Promise<void> {
  await apiClient.post("/auth/logout");
}
