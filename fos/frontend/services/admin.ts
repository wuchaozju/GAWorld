import { apiClient } from "./client";

export type AdminUser = {
  id: number;
  email: string;
  username: string;
  full_name?: string | null;
  organization?: string | null;
  is_active: boolean;
  is_verified: boolean;
  created_at: string;
  updated_at: string;
};

export type AdminSimulation = {
  id: string;
  name: string;
  owner_id: number;
  owner_username?: string;
  scene_type: string;
  status: string;
  created_at: string;
};

export async function adminListUsers(params: {
  q?: string;
  org?: string;
  created_from?: string;
  created_to?: string;
  sort?: string; // e.g., name_asc, org_desc, created_desc
}): Promise<AdminUser[]> {
  const { data } = await apiClient.get<AdminUser[]>("admin/users", { params });
  return data;
}

export async function adminListSimulations(params: {
  user?: string; // username contains
  scene_type?: string;
  created_from?: string;
  created_to?: string;
  sort?: string; // username_asc, scene_desc, created_desc
}): Promise<AdminSimulation[]> {
  const { data } = await apiClient.get<AdminSimulation[]>("admin/simulations", { params });
  return data;
}

export type AdminStats = {
  period: "day" | "week" | "month";
  sim_runs: { date: string; count: number }[];
  user_visits: { date: string; count: number }[];
  user_signups: { date: string; count: number }[];
};

export async function adminGetStats(period: "day" | "week" | "month"): Promise<AdminStats> {
  const { data } = await apiClient.get<AdminStats>("admin/stats", { params: { period } });
  return data;
}

export async function adminUpdateUserRole(userId: number, role: 'user' | 'admin'): Promise<AdminUser> {
  const { data } = await apiClient.patch<AdminUser>(`admin/users/${userId}/role`, { role });
  return data;
}
