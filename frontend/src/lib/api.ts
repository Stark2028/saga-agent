import type { ApproveRunRequest, BenchmarkResponse, ChaosConfig, CreateRunRequest, ErrorResponse, ForkRunRequest, RejectRunRequest, ReviseRfqRequest, RunTraceResponse } from '../types/saga';
import { isRecord } from './format';

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details: Record<string, unknown>[] = []) {
    super(message);
    this.name = 'ApiError';
  }
  get runId(): string | undefined {
    const detail = this.details.find(item => typeof item.run_id === 'string');
    return typeof detail?.run_id === 'string' ? detail.run_id : undefined;
  }
}

export class SagaApi {
  constructor(public baseUrl = (import.meta.env.VITE_API_BASE_URL as string | undefined ?? '').replace(/\/$/, '')) {}

  async request<T>(path: string, method = 'GET', body?: unknown, token?: string): Promise<T> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 45000);
    try {
      const response = await fetch(`${this.baseUrl}${path}`, {
        method, signal: controller.signal,
        headers: { ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}), ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
      });
      let data: unknown;
      try { data = await response.json(); } catch {
        throw new ApiError(response.status, 'INVALID_RESPONSE', 'The server returned an unreadable response. Check the API address and reload the trace.');
      }
      if (!response.ok) {
        if (isRecord(data) && isRecord(data.error) && typeof data.error.code === 'string' && typeof data.error.message === 'string') {
          const error = data as unknown as ErrorResponse;
          throw new ApiError(response.status, error.error.code, error.error.message, (error.error.details ?? []).filter(isRecord));
        }
        throw new ApiError(response.status, 'HTTP_ERROR', `Request failed (${response.status}). Reload the trace before repeating an action.`);
      }
      return data as T;
    } catch (error) {
      if (error instanceof ApiError) throw error;
      throw new ApiError(0, controller.signal.aborted ? 'REQUEST_TIMED_OUT' : 'NETWORK_ERROR', controller.signal.aborted
        ? 'The request timed out. It may have committed. Reload the existing trace before repeating an action.'
        : 'Cannot reach the backend. Start FastAPI on port 8000 or check the API address.');
    } finally { clearTimeout(timer); }
  }

  create(body: CreateRunRequest) { return this.request<RunTraceResponse>('/api/runs', 'POST', body); }
  trace(id: string) { return this.request<RunTraceResponse>(`/api/runs/${encodeURIComponent(id)}/trace`); }
  resume(id: string, chaos_config?: ChaosConfig) { return this.request<RunTraceResponse>(`/api/runs/${encodeURIComponent(id)}/resume`, 'POST', chaos_config === undefined ? {} : { chaos_config }); }
  approve(id: string, body: ApproveRunRequest, token: string) { return this.request<RunTraceResponse>(`/api/runs/${encodeURIComponent(id)}/approve`, 'POST', body, token); }
  reject(id: string, body: RejectRunRequest, token: string) { return this.request<RunTraceResponse>(`/api/runs/${encodeURIComponent(id)}/reject`, 'POST', body, token); }
  revise(id: string, body: ReviseRfqRequest) { return this.request<RunTraceResponse>(`/api/runs/${encodeURIComponent(id)}/revise-rfq`, 'POST', body); }
  fork(id: string, body: ForkRunRequest) { return this.request<RunTraceResponse>(`/api/runs/${encodeURIComponent(id)}/fork`, 'POST', body); }
  scenario(id: string, chaos_config: ChaosConfig = {}) { return this.request<RunTraceResponse>(`/api/chaos/scenarios/${encodeURIComponent(id)}`, 'POST', { chaos_config }); }
  benchmarks() { return this.request<BenchmarkResponse>('/api/chaos/benchmarks'); }
}

export const api = new SagaApi();
