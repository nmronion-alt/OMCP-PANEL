// OMCP Admin workspace source (TypeScript). admin.js is the browser-ready runtime companion.
type Role = "admin" | "user";
type PanelUser = { username: string; email: string; role: Role };
type MinecraftServer = { id: string; name: string; software: string; version: string; memory: number; status: string };
type NodeRecord = { id: string; name: string; address: string };
type LocationRecord = { id: string; name: string; region: string };
type AdminMetadata = { nodes: NodeRecord[]; locations: LocationRecord[]; settings: Record<string,string> };
type ApiOptions = RequestInit & { headers?: Record<string,string> };
const sessionToken: string | null = sessionStorage.getItem("omcp-token");
async function adminApi<T>(path: string, options: ApiOptions = {}): Promise<T> {
  if (!sessionToken) { location.href = "/"; throw new Error("Please sign in again"); }
  const response = await fetch(path, { ...options, headers: { Authorization: "Bearer " + sessionToken, "X-OMCP-Session": sessionToken, "Content-Type": "application/json", ...options.headers } });
  const payload = await response.json() as T & { error?: string };
  if (!response.ok) throw new Error(payload.error || "Request failed");
  return payload;
}
export async function loadAdminWorkspace() {
  const [userData, serverData, metadata] = await Promise.all([
    adminApi<{users:PanelUser[]}>("/api/users"),
    adminApi<{servers:MinecraftServer[]}>("/api/servers"),
    adminApi<AdminMetadata>("/api/admin/metadata")
  ]);
  return { users: userData.users, servers: serverData.servers, metadata };
}