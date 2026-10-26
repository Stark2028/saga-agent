import { Check, LockKeyhole, Send, Undo2, X } from 'lucide-react';
import { useState } from 'react';
import type { ApprovalResponse, ApproveRunRequest, ChaosConfig, RejectRunRequest, RunResponse } from '../types/saga';
import { integer, isRecord, money, shortHash } from '../lib/format';
import { CopyButton, JsonView, StatusBadge } from './shared';

interface Props { run: RunResponse; approvals: ApprovalResponse[]; busy: boolean; pauseByDefault: boolean; onApprove: (body: ApproveRunRequest, token: string) => void; onReject: (body: RejectRunRequest, token: string) => void; onRevise: (raw: string) => void; }
const configuredId = (import.meta.env.VITE_REVIEWER_ID as string | undefined) || 'sales_mgr_01';
const configuredToken = (import.meta.env.VITE_REVIEWER_TOKEN as string | undefined) || 'local-reviewer-token';

export function ApprovalGateCard({ run, approvals, busy, pauseByDefault, onApprove, onReject, onRevise }: Props) {
  const approval = approvals.find(item => item.revision_no === run.active_revision_no);
  const [profile, setProfile] = useState('configured');
  const [reviewer, setReviewer] = useState(configuredId);
  const [token, setToken] = useState(configuredToken);
  const [note, setNote] = useState('Margin reviewed');
  const [pause, setPause] = useState(pauseByDefault);
  const [failCompensation, setFailCompensation] = useState(false);
  const [revised, setRevised] = useState(typeof run.rfq_payload.raw_request === 'string' ? run.rfq_payload.raw_request.replace(/^\d+/, quantity => String(Number(quantity) + 4)) : '14 x APL-001');
  const [localError, setLocalError] = useState('');
  const actor = profile === 'invalid-reviewer' ? 'wrong_reviewer' : reviewer;
  const bearer = profile === 'invalid-token' ? 'invalid-token-for-auth-test' : token;
  const pending = run.status === 'AWAITING_APPROVAL' && approval?.status === 'PENDING';
  const rejectable = run.status === 'AWAITING_APPROVAL' && approval && ['PENDING', 'APPROVED'].includes(approval.status);
  const revisable = ['AWAITING_APPROVAL', 'RUNNING', 'RECONCILING'].includes(run.status) && approval?.status !== 'CONSUMED_FOR_DISPATCH';
  const frozen = approval?.frozen_dispatch_payload;
  const total = integer(frozen?.total_amount);
  return <section className={`panel approval-panel ${pending ? 'needs-review' : ''}`} id="human-approval" tabIndex={-1} aria-labelledby="approval-title"><div className="panel-heading"><h2 id="approval-title"><LockKeyhole size={19} aria-hidden="true" /> Human approval</h2>{approval && <StatusBadge status={approval.status} />}</div>
    {!approval ? <p className="empty-inline">Approval becomes available after the draft quote is committed.</p> : <div className="panel-body">
      <div className="approval-total"><div><span className="small muted">Exact quote to approve</span><strong title={total !== null ? `${total} paise` : undefined}>{total !== null ? money(total) : '—'}</strong></div><span className="small muted">Revision {approval.revision_no}<br />{String(frozen?.recipient ?? '')}</span></div>
      {Array.isArray(frozen?.line_items) && <ul className="quote-lines">{frozen.line_items.filter(isRecord).map((item, index) => <li key={index}><span className="mono">{String(item.sku)}</span><span>Qty {String(item.qty)}</span><span title={`${String(item.unit_price)} paise`}>{typeof item.unit_price === 'number' ? money(item.unit_price) : '—'} / unit</span></li>)}</ul>}
      <div className="hash-line"><span className="small muted">SHA-256 binding</span><code title={approval.bound_state_hash}>{shortHash(approval.bound_state_hash)}</code><CopyButton value={approval.bound_state_hash} name="Copy approval hash" /></div>
      <details><summary>Frozen dispatch payload & full hash</summary><code className="full-hash">{approval.bound_state_hash}</code><JsonView value={frozen} /></details>
      <div className="form-grid review-fields"><label>Reviewer profile<select value={profile} onChange={e => setProfile(e.target.value)}><option value="configured">Configured demo · {configuredId}</option><option value="custom">Custom credentials</option><option value="invalid-token">Invalid token (test 401)</option><option value="invalid-reviewer">Wrong identity (test 403)</option></select></label><label>Reviewer identity<input required value={reviewer} onChange={e => setReviewer(e.target.value)} disabled={profile !== 'custom'} /></label></div>
      {profile === 'custom' && <label>Bearer token<input type="password" value={token} onChange={e => setToken(e.target.value)} autoComplete="off" spellCheck={false} /></label>}
      <p className="field-hint">Demo profile matches the README startup commands. Custom credentials stay in memory.</p>
      <label>Review note<input value={note} onChange={e => setNote(e.target.value)} maxLength={2000} /></label>
      <div className="review-options"><label className="check-label"><input type="checkbox" checked={pause} onChange={e => setPause(e.target.checked)} /> Pause after approval, before dispatch</label><label className="check-label"><input type="checkbox" checked={failCompensation} onChange={e => setFailCompensation(e.target.checked)} /> Fail inventory compensation (scenario 3B)</label></div>
      {localError && <p className="field-error" role="alert">{localError}</p>}
      <div className="button-row"><button className="button primary" disabled={busy || !pending || !actor.trim() || !bearer.trim()} onClick={() => { setLocalError(''); onApprove({ reviewer_id: actor, bound_revision_no: approval.revision_no, bound_state_hash: approval.bound_state_hash, reviewer_note: note, auto_execute_dispatch: !pause }, bearer); }}>{pause ? <Check size={15} aria-hidden="true" /> : <Send size={15} aria-hidden="true" />}{pause ? 'Approve & pause' : 'Approve & dispatch'}</button>
        <button className="button danger-outline" disabled={busy || !rejectable || !actor.trim() || !bearer.trim()} onClick={() => { if (!note.trim()) { setLocalError('Add a review note before rejecting.'); return; } const chaos: ChaosConfig = failCompensation ? { fail_compensation_on_step: 1 } : {}; setLocalError(''); onReject({ reviewer_id: actor, reviewer_note: note, chaos_config: chaos }, bearer); }}><X size={15} aria-hidden="true" /> Reject & roll back</button></div>
      {approval.status === 'APPROVED' && <p className="instruction">Approval recorded. Resume to dispatch, or revise the RFQ to invalidate this approval.</p>}
      <form className="revision-form" onSubmit={event => { event.preventDefault(); onRevise(revised); }}><label>Revise customer RFQ<input value={revised} onChange={e => setRevised(e.target.value)} required maxLength={20000} disabled={!revisable} /></label><button className="button subtle" disabled={busy || !revisable} type="submit"><Undo2 size={14} aria-hidden="true" /> Revise RFQ</button></form>
      {!revisable && <p className="field-hint">Revisions close when terminal dispatch is claimed.</p>}
      {approvals.length > 1 && <details><summary>Approval history ({approvals.length})</summary><ul className="approval-history">{approvals.map(record => <li key={record.id}><span>Revision {record.revision_no}</span><StatusBadge status={record.status} /><code title={record.bound_state_hash}>{shortHash(record.bound_state_hash)}</code></li>)}</ul></details>}
    </div>}
  </section>;
}
