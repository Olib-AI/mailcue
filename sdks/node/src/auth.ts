export interface AuthConfig {
  apiKey?: string;
  bearerToken?: string;
}

export function buildAuthHeaders(auth: AuthConfig): Record<string, string> {
  if (auth.apiKey) {
    return { 'X-API-Key': auth.apiKey };
  }
  if (auth.bearerToken) {
    return { Authorization: `Bearer ${auth.bearerToken}` };
  }
  return {};
}
