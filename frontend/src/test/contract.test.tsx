import { afterEach, expect, test, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import example from '../../../backend/examples/run-trace.json';
import { ApprovalGateCard } from '../components/ApprovalGateCard';
import { ApiError, SagaApi } from '../lib/api';
import { money } from '../lib/format';
import { focusedStep } from '../lib/execution';
import type { RunTraceResponse } from '../types/saga';

afterEach(() => vi.unstubAllGlobals());

test('pending human review focuses the gate even after its runtime step commits', () => {
  const trace = structuredClone(example) as RunTraceResponse;
  trace.run.status = 'AWAITING_APPROVAL';
  trace.approvals[0].status = 'PENDING';
  trace.steps.forEach(step => { step.status = step.step_index <= 3 ? 'COMMITTED' : 'PENDING'; step.compensation_status = 'NOT_NEEDED'; });
  expect(focusedStep(trace)?.step_index).toBe(3);
  trace.approvals[0].status = 'APPROVED';
  expect(focusedStep(trace)?.step_index).toBe(4);
});

test('an unresolved effect takes priority over the next pending step', () => {
  const trace = structuredClone(example) as RunTraceResponse;
  trace.run.status = 'RECONCILING';
  trace.steps.forEach(step => { step.status = step.step_index < 2 ? 'COMMITTED' : 'PENDING'; step.compensation_status = 'NOT_NEEDED'; });
  trace.steps.find(step => step.step_index === 2)!.status = 'OUTCOME_UNKNOWN';
  expect(focusedStep(trace)?.step_index).toBe(2);
});

test('failed compensation remains visible when it belongs to a superseded revision', () => {
  const trace = structuredClone(example) as RunTraceResponse;
  trace.run.status = 'FAILED_NEEDS_HUMAN';
  trace.run.active_revision_no = 2;
  trace.steps.forEach(step => { step.status = 'COMMITTED'; step.compensation_status = 'NOT_NEEDED'; });
  const failed = trace.steps.find(step => step.step_index === 1)!;
  failed.compensation_status = 'COMPENSATION_FAILED';
  expect(focusedStep(trace)?.id).toBe(failed.id);
});

test.each(['COMPLETED', 'COMPENSATED_HALTED'] as const)('terminal %s has no suggested next step', status => {
  const trace = structuredClone(example) as RunTraceResponse;
  trace.run.status = status;
  expect(focusedStep(trace)).toBeUndefined();
});

test('renders paise as INR and keeps the technical integer available', () => {
  expect(money(125000)).toContain('1,250.00');
  const trace = structuredClone(example) as RunTraceResponse;
  trace.run.status = 'AWAITING_APPROVAL';
  trace.approvals[0].status = 'PENDING';
  const onApprove = vi.fn();
  render(<ApprovalGateCard run={trace.run} approvals={trace.approvals} busy={false} pauseByDefault={false} onApprove={onApprove} onReject={vi.fn()} onRevise={vi.fn()} />);
  const amount = screen.getByText(money(trace.approvals[0].frozen_dispatch_payload.total_amount as number));
  expect(amount).toHaveAttribute('title', `${trace.approvals[0].frozen_dispatch_payload.total_amount} paise`);
  fireEvent.click(screen.getByRole('button', { name: 'Approve & dispatch' }));
  expect(onApprove).toHaveBeenCalledWith(expect.objectContaining({ bound_state_hash: trace.run.state_hash, bound_revision_no: 1, reviewer_id: 'sales_mgr_01' }), 'local-reviewer-token');
});

test('extracts the persisted run ID from a crash ErrorResponse', async () => {
  const runId = '1e606684-5690-4c99-b961-46316322889b';
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ error: { code: 'SIMULATED_WORKER_CRASH', message: 'worker stopped', details: [{ run_id: runId }] } }), { status: 503, headers: { 'Content-Type': 'application/json' } })));
  const client = new SagaApi('/api');
  await expect(client.scenario('rfq_01', { crash_worker_after_step_in_flight: 1 })).rejects.toMatchObject({ status: 503, code: 'SIMULATED_WORKER_CRASH', runId });
});

test('preserves explicit authentication failures for the operator', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ error: { code: 'INVALID_CREDENTIALS', message: 'Invalid reviewer bearer token', details: [] } }), { status: 401, headers: { 'Content-Type': 'application/json' } })));
  try { await new SagaApi('/api').approve('run', { reviewer_id: 'manager', bound_revision_no: 1, bound_state_hash: 'a'.repeat(64) }, 'bad'); }
  catch (error) { expect(error).toBeInstanceOf(ApiError); expect(error).toMatchObject({ status: 401, code: 'INVALID_CREDENTIALS' }); return; }
  throw new Error('Expected the API to reject the invalid token');
});
