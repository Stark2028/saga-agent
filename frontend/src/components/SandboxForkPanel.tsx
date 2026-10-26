import { GitFork } from 'lucide-react';
import { useState } from 'react';
import type { ForkRunRequest, RunTraceResponse } from '../types/saga';
import { isRecord, shortId } from '../lib/format';
import { JsonView } from './shared';

export function SandboxForkPanel({ trace, busy, onFork }: { trace: RunTraceResponse; busy: boolean; onFork: (body: ForkRunRequest) => void }) {
  const [index, setIndex] = useState(1);
  const [revision, setRevision] = useState(trace.run.active_revision_no);
  const [override, setOverride] = useState('');
  const [error, setError] = useState('');
  return <section className="panel fork-panel" id="sandbox-fork" aria-labelledby="fork-title"><div className="panel-heading"><h2 id="fork-title"><GitFork size={17} aria-hidden="true" /> Sandbox replay</h2><span className="sandbox-label">Isolated</span></div><div className="panel-body"><p className="small muted">Replay a historical checkpoint. Live service records stay unchanged.</p>
    <form className="form-stack" onSubmit={event => {
      event.preventDefault();
      let plan: Record<string, unknown> | undefined;
      if (override.trim()) { try { const parsed: unknown = JSON.parse(override); if (!isRecord(parsed)) throw new Error(); plan = parsed; } catch { setError('Override plan must be a JSON object.'); return; } }
      if (plan && index > 1) { setError('Changed plans must fork before inventory reservation: select step 0 or 1.'); return; }
      setError(''); onFork({ from_step_index: index, revision_no: revision, ...(plan ? { override_plan: plan } : {}) });
    }}>
      <div className="form-grid"><label>Revision<select value={revision} onChange={e => setRevision(Number(e.target.value))}>{trace.revisions.map(row => <option key={row.revision_no} value={row.revision_no}>Revision {row.revision_no}</option>)}</select></label><label>Before step<select value={index} onChange={e => setIndex(Number(e.target.value))}><option value={0}>0 · Parse RFQ</option><option value={1}>1 · Reserve stock</option><option value={2}>2 · Draft quote</option><option value={3}>3 · Approval gate</option></select></label></div>
      <details><summary>Override plan (optional)</summary><label className="sr-only" htmlFor="override-plan">Override plan JSON</label><textarea className="mono" id="override-plan" value={override} onChange={e => setOverride(e.target.value)} rows={5} placeholder={JSON.stringify(trace.run.agent_plan, null, 2)} /><p className="field-hint">Use the complete plan with catalogue prices and matching integer totals.</p></details>
      {error && <p className="field-error" role="alert">{error}</p>}
      <button className="button subtle full" disabled={busy || trace.checkpoints_count === 0} type="submit"><GitFork size={15} aria-hidden="true" /> Fork to sandbox</button>
    </form>
    <div className="fork-provenance"><span className="small muted">{trace.checkpoints_count} recorded checkpoints</span>{trace.run.parent_run_id && <p className="small">Forked from <code title={trace.run.parent_run_id}>{shortId(trace.run.parent_run_id)}</code> before step {trace.run.forked_from_step_index}</p>}<details><summary>Namespace & source record map</summary><code className="full-hash">{trace.run.sandbox_namespace}</code><JsonView value={trace.run.source_record_map} /></details></div>
  </div></section>;
}
