import { Check, Copy } from 'lucide-react';
import { useState } from 'react';
import { label } from '../lib/format';

export function StatusBadge({ status }: { status: string }) {
  const tone = ['COMPLETED', 'COMMITTED', 'APPROVED', 'COMPENSATED', 'COMMITTED_CONVERTED', 'SENT'].includes(status) ? 'success'
    : ['FAILED_NEEDS_HUMAN', 'FAILED_VERIFICATION', 'BLOCKED', 'COMPENSATION_FAILED', 'FAILED_TERMINAL', 'REJECTED'].includes(status) ? 'danger'
    : ['NEEDS_CLARIFICATION', 'PLANNING', 'OUTCOME_UNKNOWN', 'RECONCILING', 'AWAITING_APPROVAL', 'IN_FLIGHT', 'DISPATCHING_FINAL', 'COMPENSATING'].includes(status) ? 'warning' : 'neutral';
  return <span className={`status-badge ${tone}`} title={status}><span aria-hidden="true" className="status-dot" />{label(status)}</span>;
}

export function JsonView({ value, title }: { value: unknown; title?: string }) {
  return <div className="json-view">{title && <h4>{title}</h4>}<pre tabIndex={0}>{JSON.stringify(value, null, 2)}</pre></div>;
}

export function CopyButton({ value, name = 'Copy ID' }: { value: string; name?: string }) {
  const [copied, setCopied] = useState(false);
  const [failed, setFailed] = useState(false);
  return <><button className="icon-button" type="button" aria-label={name} title={name} onClick={() => {
    void navigator.clipboard?.writeText(value).then(() => { setCopied(true); setFailed(false); }).catch(() => setFailed(true));
    if (!navigator.clipboard) setFailed(true);
  }}>{copied ? <Check size={14} aria-hidden="true" /> : <Copy size={14} aria-hidden="true" />}</button>{failed && <span className="small muted" role="status">Select the ID to copy.</span>}</>;
}
