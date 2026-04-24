const BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

export async function login(username, password) {
  const form = new URLSearchParams({ username, password });
  const res = await fetch(`${BASE}/api/auth/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: form,
  });
  if (!res.ok) throw new Error("Login failed");
  const data = await res.json();
  localStorage.setItem("oee_token", data.access_token);
  return data.access_token;
}

export function getToken() {
  return localStorage.getItem("oee_token");
}

export function logout() {
  localStorage.removeItem("oee_token");
  window.location.reload();
}

export function authHeader() {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}
