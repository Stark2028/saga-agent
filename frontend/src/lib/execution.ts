import type { RunTraceResponse } from '../types/saga';

/** Keep the visual focus on the boundary that needs attention, including old-revision rollback. */
export function focusedStep(trace: RunTraceResponse) {
  if (['COMPLETED', 'COMPENSATED_HALTED'].includes(trace.run.status)) return undefined;
  const failed = [...trace.steps].reverse().find(step => step.status.includes('FAILED') || step.compensation_status === 'COMPENSATION_FAILED');
  if (failed) return failed;
  const current = trace.steps.filter(step => step.revision_no === trace.run.active_revision_no);
  const unresolved = current.find(step => ['IN_FLIGHT', 'OUTCOME_UNKNOWN', 'COMPENSATING'].includes(step.status));
  if (unresolved) return unresolved;
  if (trace.run.status === 'AWAITING_APPROVAL') {
    const approval = trace.approvals.find(item => item.revision_no === trace.run.active_revision_no);
    return current.find(step => step.step_index === (approval?.status === 'PENDING' ? 3 : 4));
  }
  return current.find(step => step.status === 'PENDING');
}
