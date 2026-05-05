import { API_BASE_URL } from "./claims-api";

export interface LoginResponse {
  token: string;
  role: "member" | "staff";
  name: string;
  sub: string;
}

export async function loginUser(username: string, password: string): Promise<LoginResponse> {
  const res = await fetch(`${API_BASE_URL}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) {
    throw new Error("Invalid credentials. Please check your details and try again.");
  }
  return res.json() as Promise<LoginResponse>;
}

export function getAuthToken(): string | null {
  try {
    const raw = localStorage.getItem("claims_auth_user");
    if (!raw) return null;
    const u = JSON.parse(raw) as { token?: string };
    return u.token ?? null;
  } catch {
    return null;
  }
}
