export type ProviderType = "telegram" | "slack" | "mattermost" | "twilio" | "whatsapp" | "discord";

export interface SandboxProvider {
  id: string;
  user_id: string;
  provider_type: ProviderType;
  name: string;
  credentials: Record<string, string>;
  is_active: boolean;
  created_at: string;
  updated_at: string | null;
  sandbox_url?: string;
}

export interface SandboxConversation {
  id: string;
  provider_id: string;
  external_id: string;
  name: string | null;
  conversation_type: string;
  metadata_json: Record<string, unknown>;
  created_at: string;
}

export interface SandboxMessage {
  id: string;
  provider_id: string;
  conversation_id: string | null;
  direction: "inbound" | "outbound";
  sender: string;
  content: string;
  content_type: string;
  external_id: string | null;
  raw_request: Record<string, unknown>;
  raw_response: Record<string, unknown>;
  metadata_json: Record<string, unknown>;
  is_deleted: boolean;
  created_at: string;
}

export interface SandboxMessageList {
  messages: SandboxMessage[];
  total: number;
}

export interface CreateProviderRequest {
  provider_type: ProviderType;
  name: string;
  credentials: Record<string, string>;
}

export interface UpdateProviderRequest {
  name?: string;
  credentials?: Record<string, string>;
  is_active?: boolean;
}

export interface SimulateRequest {
  sender: string;
  content: string;
  content_type?: string;
  conversation_id?: string;
  metadata?: Record<string, unknown>;
  conversation_name?: string;
}

export interface SendRequest {
  sender?: string;
  content: string;
  content_type?: string;
  conversation_id?: string;
  conversation_name?: string;
  metadata?: Record<string, unknown>;
}

export interface WebhookEndpoint {
  id: string;
  provider_id: string;
  url: string;
  secret: string | null;
  event_types: string[];
  is_active: boolean;
  created_at: string;
}

export interface WebhookDelivery {
  id: string;
  endpoint_id: string;
  message_id: string | null;
  event_type: string;
  payload: Record<string, unknown>;
  status_code: number | null;
  response_body: string | null;
  attempt: number;
  delivered_at: string | null;
  created_at: string;
}

export interface CreateWebhookRequest {
  url: string;
  secret?: string;
  event_types?: string[];
}
