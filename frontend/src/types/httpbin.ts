export interface HttpBinBin {
  id: string;
  user_id: string;
  name: string;
  response_status_code: number;
  response_body: string | null;
  response_content_type: string;
  created_at: string;
  request_count: number;
}

export interface HttpBinCapturedRequest {
  id: string;
  bin_id: string;
  method: string;
  path: string;
  headers: Record<string, string>;
  query_params: Record<string, string>;
  body: string | null;
  content_type: string | null;
  remote_addr: string | null;
  created_at: string;
}

export interface HttpBinCapturedRequestList {
  requests: HttpBinCapturedRequest[];
  total: number;
}

export interface CreateBinRequest {
  name: string;
  response_status_code?: number;
  response_body?: string;
  response_content_type?: string;
}

export interface UpdateBinRequest {
  name?: string;
  response_status_code?: number;
  response_body?: string;
  response_content_type?: string;
}
