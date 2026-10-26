import { ArrowDown, ArrowUpRight, Check, CircleAlert, RefreshCw, RotateCcw, ShieldCheck } from 'lucide-react';
import type { RunResponse } from '../types/saga';
import { dateTime, shortId } from '../lib/format';
import { CopyButton, StatusBadge } from './shared';

interface Props { run: RunResponse; busy: boolean; waitingForReview: boolean; onResume: () => void; onRefresh: () => void; onParent: (id: string) => void; onInspectFocus: (() => void) | undefined; }

export function RunHeaderBar({ run, busy, waitingForReview, onResume, onRefresh, onParent, onInspectFocus }: Props) {
  const terminal = ['COMPLETED', 'COMPENSATED_HALTED'].includes(run.status);
  const leased = run.lease_owner !== null && run.lease_expires_at !== null && new Date(run.lease_expires_at).getTime() > Date.now();
  const needsHuman = run.status === 'FAILED_NEEDS_HUMAN';
  const uncertain = run.status === 'RECONCILING';
  const title = waitingForReview ? 'Your review is the next step' : leased ? 'A worker is executing this run' : run.status === 'COMPLETED' ? 'Execution complete' : run.status === 'COMPENSATED_HALTED' ? 'Rollback complete' : needsHuman ? 'This run needs your attention' : uncertain ? 'Verify the outcome to continue' : run.status === 'AWAITING_APPROVAL' ? 'Ready for dispatch' : 'Continue from the saved boundary';
  const description = waitingForReview ? 'Check the frozen quote below. Dispatch stays paused until you approve.' : leased ? 'Refresh the trace for its latest state. The active lease prevents another worker from taking over.' : run.status === 'COMPLETED' ? 'The approved quote was dispatched and finalization is recorded in the trace.' : run.status === 'COMPENSATED_HALTED' ? 'The run is halted and its compensatable effects have been reversed.' : needsHuman ? 'Inspect the affected step and resource IDs before attempting recovery.' : uncertain ? 'Reconcile the external effect before deciding whether another attempt is safe.' : run.status === 'AWAITING_APPROVAL' ? 'Resume to dispatch the approved quote, or revise the RFQ for a fresh review.' : 'Resume uses the durable trace to determine the next safe action.';
  const Icon = terminal ? Check : waitingForReview ? ShieldCheck : needsHuman || uncertain ? CircleAlert : RotateCcw;
  return <section className="run-header" aria-label="Current execution">
    <div className="run-heading"><div className="inline"><span className={`mode-label ${run.execution_mode === 'SANDBOX' ? 'sandbox' : ''}`}>{run.execution_mode}</span><h2>Run <span className="mono" title={run.id}>{shortId(run.id)}</span></h2><CopyButton value={run.id} /><StatusBadge status={run.status} /></div>
      <button className="button subtle" disabled={busy} onClick={onRefresh}><RefreshCw size={16} aria-hidden="true" /> Refresh</button></div>
    <div className="run-metadata"><span>Revision <strong>{run.active_revision_no}</strong></span><span>Version <strong>{run.version}</strong></span><span title={run.lease_expires_at ? dateTime(run.lease_expires_at) : undefined}>Lease <strong>{leased ? 'Active worker' : 'Available'}</strong></span><span>Updated {dateTime(run.updated_at)}</span>{run.parent_run_id && <button className="text-button" disabled={busy} onClick={() => onParent(run.parent_run_id!)}>Parent {shortId(run.parent_run_id)}<ArrowUpRight size={14} aria-hidden="true" /></button>}</div>
    <div className={`run-focus ${needsHuman ? 'attention' : uncertain ? 'uncertain' : ''}`} key={`${run.id}:${run.status}:${waitingForReview}`}>
      <span className="focus-symbol"><Icon size={23} aria-hidden="true" /></span><div className="focus-copy"><h3>{title}</h3><p>{description}</p></div>
      {waitingForReview ? <button className="button primary" disabled={busy} onClick={() => { const panel = document.getElementById('human-approval'); panel?.focus({ preventScroll: true }); panel?.scrollIntoView({ behavior: 'smooth', block: 'start' }); }}>Review quote<ArrowDown size={16} aria-hidden="true" /></button>
        : !terminal && <div className="button-row">{needsHuman && onInspectFocus && <button className="button primary" onClick={onInspectFocus}>Inspect affected step</button>}<button className={`button ${needsHuman ? 'subtle' : 'primary'}`} disabled={busy || leased} onClick={onResume}><RotateCcw size={16} aria-hidden="true" />{uncertain ? 'Resume / Reconcile' : 'Resume run'}</button></div>}
    </div>
    {run.error_summary && <div className="run-error" role="status"><strong>Operator attention required</strong><code>{run.error_summary}</code></div>}
  </section>;
}
