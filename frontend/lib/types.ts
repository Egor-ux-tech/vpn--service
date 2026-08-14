export type UserStatus = "active" | "blocked";
export type VPNServerStatus = "online" | "degraded" | "offline" | "maintenance";
export type PaymentStatus = "pending" | "succeeded" | "failed" | "refunded" | "cancelled";
export type RouteType = "vpn" | "direct";

export interface UserRead {
  id: number;
  telegram_id: number;
  username: string | null;
  first_name: string | null;
  last_name: string | null;
  status: UserStatus;
  created_at: string;
}

export interface VPNServerRead {
  id: number;
  name: string;
  country: string;
  city: string | null;
  hostname: string;
  endpoint: string;
  status: VPNServerStatus;
  capacity: number;
  current_load: number;
}

export interface RoutingCategoryRead {
  id: number;
  name: string;
  description: string | null;
  enabled: boolean;
}

export interface RoutingRuleRead {
  id: number;
  category_id: number;
  domain: string;
  route_type: RouteType;
  enabled: boolean;
}

export interface PaymentRead {
  id: number;
  user_id: number;
  plan_id: number;
  provider: string;
  amount: string;
  currency: string;
  status: PaymentStatus;
}

export interface AuditLogRead {
  id: number;
  admin_id: number | null;
  action: string;
  target_type: string;
  target_id: string | null;
  metadata_json: Record<string, unknown>;
  created_at: string;
}

export interface DashboardStats {
  total_users: number;
  active_subscriptions: number;
  active_devices: number;
  online_servers: number;
  online_peers: number;
  revenue_last_30d: number;
  open_support_tickets: number;
}

export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    details?: unknown;
    request_id?: string;
  };
}
