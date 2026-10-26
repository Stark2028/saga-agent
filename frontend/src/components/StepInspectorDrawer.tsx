import { useEffect, useRef } from 'react';
import { X } from 'lucide-react';
import type { AttemptResponse, StepResponse } from '../types/saga';
import { dateTime, label } from '../lib/format';
import { CopyButton, JsonView, StatusBadge } from './shared';

export function StepInspectorDrawer({ step, attempts, onClose }: { step: StepResponse | null; attempts: AttemptResponse[]; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const current = dialog.current;
    if (!current) return;
    if (step && !current.open) current.showModal();
    if (!step && current.open) current.close();
  }, [step]);
  return <dialog ref={dialog} className="inspector" aria-labelledby="inspector-title" onCancel={onClose} onClick={event => { if (event.target === event.currentTarget) onClose(); }}>
    {step && <><div className="inspector-heading"><div><h2 id="inspector-title">{label(step.step_name)}</h2><span className="small muted">Revision {step.revision_no} · Step {step.step_index} · {step.tool_name}</span></div><button className="icon-button" aria-label="Close step inspector" onClick={onClose}><X size={20} aria-hidden="true" /></button></div>
      <div className="inspector-content"><StatusBadge status={step.status} /><dl className="inspector-facts"><div><dt>Operation ID</dt><dd className="mono">{step.operation_id}<CopyButton value={step.operation_id} name="Copy operation ID" /></dd></div><div><dt>External record</dt><dd className="mono">{step.external_record_id ?? 'No external record'}</dd></div><div><dt>Compensation operation</dt><dd className="mono">{step.compensation_operation_id}</dd></div><div><dt>Attempts / reconciliation polls</dt><dd>{step.attempt_count} / {step.reconcile_polls}</dd></div><div><dt>Compensation</dt><dd>{label(step.compensation_status)} · {step.compensation_attempt_count} attempts</dd></div></dl>
        {step.error_detail && <p className="run-error">{step.error_detail}</p>}
        <JsonView title="Verification evidence" value={step.verification_evidence} /><JsonView title="Compensation evidence" value={step.compensation_evidence} /><JsonView title="Input payload (raw paise)" value={step.input_payload} /><JsonView title="Output payload" value={step.output_payload} />
        <h3 className="timeline-title">Attempt timeline</h3><ol className="attempt-timeline">{attempts.filter(a => a.step_id === step.id).sort((a, b) => a.created_at.localeCompare(b.created_at)).map(attempt => <li key={attempt.id}><div className="inline"><strong>{label(attempt.event)}</strong><span className="small muted">{attempt.kind} #{attempt.attempt_no}</span></div><time className="small muted" dateTime={attempt.created_at}>{dateTime(attempt.created_at)}</time><details><summary>Evidence</summary><JsonView value={attempt.evidence} /></details></li>)}</ol>{!attempts.some(a => a.step_id === step.id) && <p className="small muted">No external attempts recorded for this planning or approval step.</p>}
      </div></>}
  </dialog>;
}
