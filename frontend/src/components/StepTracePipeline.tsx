import { Check, Circle, CircleAlert, HelpCircle, RotateCcw, ShieldCheck, Undo2 } from 'lucide-react';
import type { StepResponse, RevisionResponse } from '../types/saga';
import { label, money, integer } from '../lib/format';

const names = ['Parse RFQ', 'Reserve stock', 'Draft quote', 'Approval gate', 'Send email', 'Finalize'];
interface Props { steps: StepResponse[]; revisions: RevisionResponse[]; activeRevision: number; focusedStepId?: string; waitingForReview: boolean; onInspect: (step: StepResponse) => void; }

export function StepTracePipeline({ steps, revisions, activeRevision, focusedStepId, waitingForReview, onInspect }: Props) {
  return <section className="panel trace-panel" aria-labelledby="trace-title"><div className="panel-heading"><h2 id="trace-title">Execution trace</h2><span className="small muted">Select any step to inspect its evidence</span></div>
    {revisions.map(revision => {
      const rows = steps.filter(step => step.revision_no === revision.revision_no).sort((a, b) => a.step_index - b.step_index);
      const total = integer(revision.agent_plan.total_amount);
      return <div className={`revision-trace ${revision.revision_no !== activeRevision ? 'historical' : ''}`} key={revision.revision_no}><div className="revision-heading"><h3>Revision {revision.revision_no} {revision.revision_no === activeRevision && <span className="current-label">Current</span>}</h3><span className="small muted">{total !== null && <span title={`${total} paise`}>{money(total)} · </span>}{label(revision.status)}</span></div>
        {rows.length ? <ol className="step-pipeline">{rows.map(step => {
          const focused = step.id === focusedStepId;
          const review = focused && waitingForReview && step.step_index === 3;
          const recovered = step.status === 'COMMITTED' && step.verification_evidence.status === 'APPLIED';
          const failed = step.status.includes('FAILED') || step.compensation_status === 'COMPENSATION_FAILED';
          const Icon = review ? ShieldCheck : failed ? CircleAlert : step.status === 'COMPENSATED' ? Undo2 : recovered ? ShieldCheck : step.status === 'COMMITTED' ? Check : step.status === 'OUTCOME_UNKNOWN' ? HelpCircle : step.status === 'IN_FLIGHT' ? RotateCcw : Circle;
          const tone = failed ? 'failed' : review ? 'review' : step.status === 'COMMITTED' ? 'committed' : step.status === 'COMPENSATED' ? 'compensated' : ['OUTCOME_UNKNOWN', 'IN_FLIGHT', 'COMPENSATING'].includes(step.status) ? 'uncertain' : 'pending';
          return <li key={step.id} className={`trace-position ${tone}`}><button className={`step-node ${tone} ${focused ? 'focused' : ''}`} aria-current={focused ? 'step' : undefined} onClick={() => onInspect(step)} aria-label={`Inspect revision ${step.revision_no} step ${step.step_index}: ${names[step.step_index]}`}>
            <span className="step-node-top"><span className="step-number">Step {String(step.step_index).padStart(2, '0')}</span><Icon size={19} aria-hidden="true" /></span>
            <span className="step-name"><strong>{names[step.step_index]}</strong><span className="step-status" title={step.status}>{label(step.status)}</span></span>
            <span className="step-details"><span className="step-counts">{step.attempt_count} {step.attempt_count === 1 ? 'attempt' : 'attempts'} · {step.reconcile_polls} {step.reconcile_polls === 1 ? 'poll' : 'polls'}</span>{step.compensation_status !== 'NOT_NEEDED' && <span className="comp-status">Undo: {label(step.compensation_status)}</span>}</span>
            {(focused || recovered) && <span className="step-marker">{review ? 'Review needed' : focused ? 'Needs attention' : 'Reconciled'}</span>}
          </button></li>;
        })}</ol> : <div className="empty-inline">Waiting for the previous revision’s compensation before allocating steps.</div>}
      </div>;
    })}
  </section>;
}
