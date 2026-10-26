import { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowRight, Check, CircleAlert, FileText, LoaderCircle, Play, RefreshCw, ShieldCheck, Upload } from 'lucide-react';
import { api } from '../lib/api';
import { label, money, shortId } from '../lib/format';
import type { AgentCapabilities, TaskResponse, TaskRecordResponse } from '../types/saga';
import { ApprovalGateCard } from '../components/ApprovalGateCard';
import { WorkspaceHeader } from '../components/WorkspaceHeader';
import { JsonView, StatusBadge } from '../components/shared';

const examples = [
  { label: 'Prepare a quote', goal: 'Prepare a quote for 10 laptops for Acme under INR 20000. Ask me before sending.' },
  { label: 'Ask for clarification', goal: 'Prepare a quote for Acme.' },
  { label: 'Inspect inventory', goal: 'Inspect current inventory availability.' },
];

export default function TaskWorkspace() {
  const [goal, setGoal] = useState(examples[0].goal);
  const [document, setDocument] = useState('');
  const [sourceName, setSourceName] = useState('');
  const [mode, setMode] = useState<'offline' | 'openai'>('offline');
  const [fault, setFault] = useState('none');
  const [answer, setAnswer] = useState('');
  const [result, setResult] = useState<TaskResponse | null>(null);
  const [recent, setRecent] = useState<TaskRecordResponse[]>([]);
  const [capabilities, setCapabilities] = useState<AgentCapabilities | null>(null);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const locked = useRef(false);
  const mounted = useRef(true);

  const remember = useCallback((value: TaskResponse) => {
    if (!mounted.current) return;
    setResult(value); setAnswer('');
    const url = new URL(window.location.href); url.searchParams.set('task', value.task.id); window.history.replaceState(null, '', url);
    void api.tasks().then(tasks => { if (mounted.current) setRecent(tasks); }).catch(() => { /* Current task remains available if history reload fails. */ });
  }, []);

  const command = useCallback(async (name: string, action: () => Promise<TaskResponse>) => {
    if (locked.current) return;
    locked.current = true; setBusy(name); setError('');
    try { remember(await action()); }
    catch (issue) { if (mounted.current) setError(issue instanceof Error ? issue.message : 'The action failed. Reload the task before trying again.'); }
    finally { locked.current = false; if (mounted.current) setBusy(''); }
  }, [remember]);

  useEffect(() => {
    mounted.current = true;
    void api.capabilities().then(value => { if (mounted.current) setCapabilities(value); }).catch(() => { if (mounted.current) setError('Start the backend on port 8000 to connect the task worker.'); });
    void api.tasks().then(tasks => { if (mounted.current) setRecent(tasks); }).catch(() => { /* Capabilities request reports connection errors. */ });
    const id = new URL(window.location.href).searchParams.get('task');
    if (id) void command('Load task', () => api.task(id));
    return () => { mounted.current = false; };
  }, [command]);

  const task = result?.task;
  const trace = result?.trace;
  const canClarify = task && !task.run_id && ['NEEDS_CLARIFICATION', 'BLOCKED'].includes(task.status);
  const canContinue = task && (['RUNNING', 'RECONCILING', 'DISPATCHING_FINAL'].includes(task.status) || (task.status === 'AWAITING_APPROVAL' && trace?.approvals.some(item => item.revision_no === trace.run.active_revision_no && item.status === 'APPROVED')));
  return <><WorkspaceHeader active="task" /><main className="worker-shell">
    <div className="worker-title"><div><h1>Give it a goal.<br />Follow the work.</h1><p>A bounded quotation worker that reads context, checks policy, acts, and verifies its records.</p></div><a className="button subtle" href="/company">Open company workspace<ArrowRight size={16} aria-hidden="true" /></a></div>
    <div className="worker-layout"><aside className="task-input panel"><div className="panel-heading"><h2>New task</h2><span className="mode-label">Sandbox company</span></div><form className="panel-body form-stack" onSubmit={event => { event.preventDefault(); const chaos = fault === 'lost' ? { drop_response_after_write_on_step: 2 } : fault === 'crash' ? { crash_after_external_commit_on_step: 1 } : {}; void command('Execute task', () => api.startTask({ goal, source_document: document, source_name: sourceName, planner_mode: mode, chaos_config: chaos })); }}>
      <label>Your objective<textarea aria-label="Your objective" rows={5} required minLength={5} maxLength={4000} value={goal} onChange={e => setGoal(e.target.value)} /></label>
      <div className="task-examples" aria-label="Task examples">{examples.map(example => <button className="example-button" type="button" key={example.label} onClick={() => setGoal(example.goal)}>{example.label}</button>)}</div>
      <label>Planner mode<select value={mode} onChange={e => setMode(e.target.value as 'offline' | 'openai')}><option value="offline">Offline · bounded language parser</option><option value="openai" disabled={!capabilities?.openai_configured}>OpenAI · {capabilities?.openai_configured ? capabilities.model : 'backend configuration required'}</option></select></label>
      <p className="field-hint">{mode === 'offline' ? 'No model is called. This demo understands explicit quantities, catalogue categories, customer names and INR budgets.' : 'Your goal, source text and company context are sent to the configured OpenAI model. Backend code validates its proposal and controls every business action.'}</p>
      <details className="source-details"><summary><FileText size={16} aria-hidden="true" /> Add an RFQ document</summary><div className="form-stack"><label className="file-upload"><Upload size={16} aria-hidden="true" /> Upload text or Markdown<input type="file" accept=".txt,.md,text/plain,text/markdown" onChange={async event => { const file = event.target.files?.[0]; if (!file) return; if (file.size > 48000) { setError('Choose a text document smaller than 48 kB.'); return; } try { const text = await file.text(); if (text.length > 12000) { setError('Document text must be at most 12,000 characters.'); return; } setDocument(text); setSourceName(file.name); setError(''); } catch { setError('Could not read the file. Paste its text below.'); } }} /></label><label>Source document text<textarea rows={5} value={document} maxLength={12000} onChange={e => { setDocument(e.target.value); if (!sourceName) setSourceName('pasted-rfq.txt'); }} /></label>{sourceName && <span className="small muted">{sourceName} · {document.length} characters</span>}</div></details>
      <details className="source-details"><summary>Recovery demonstration</summary><label>Fault to inject<select value={fault} onChange={e => setFault(e.target.value)}><option value="none">None</option><option value="lost">Lose the CRM write response</option><option value="crash">Crash after inventory commits</option></select></label><p className="field-hint">The controller observes the durable boundary and attempts bounded recovery automatically.</p></details>
      <button className="button primary full" disabled={!!busy || !capabilities} type="submit">{busy ? <LoaderCircle className="spin" size={17} aria-hidden="true" /> : <Play size={17} aria-hidden="true" />}{busy || 'Execute task'}</button>
      <p className="small muted">All business records are local mock data. Sending always requires authenticated human approval.</p>
    </form></aside>
    <div className="task-work"><div className="feedback-area" aria-live="polite">{busy && <p className="progress-message"><LoaderCircle className="spin" size={16} aria-hidden="true" />{busy}…</p>}</div>{error && <div className="error-banner" role="alert"><CircleAlert size={18} aria-hidden="true" /><p>{error}</p></div>}
      {result && task ? <>
        <section className="task-outcome panel" aria-labelledby="task-outcome-title"><div className="panel-heading"><h2 id="task-outcome-title">Task {shortId(task.id)}</h2><StatusBadge status={task.status} /></div><div className="panel-body"><div className="task-outcome-heading"><ShieldCheck size={25} aria-hidden="true" /><p>{result.summary}</p></div><div className="task-context-line"><span>{task.planner_mode === 'offline' ? 'Offline parser · no LLM call' : `OpenAI · ${capabilities?.model ?? 'configured model'}`}</span><span>Policy v{String(task.policy_snapshot.version)}</span><span>{task.observations.length} observations</span></div>{task.error_code && <p className="field-error">{task.error_code}</p>}
        {task.questions.length > 0 && <ul className="clarification-questions">{task.questions.map(question => <li key={question}>{question}</li>)}</ul>}
        {canClarify && <form className="clarification-form" onSubmit={event => { event.preventDefault(); void command('Continue with clarification', () => api.continueTask(task.id, { answer })); }}><label>Your clarification<textarea rows={3} required value={answer} onChange={e => setAnswer(e.target.value)} placeholder="For example: 10 laptops for Acme, under INR 20000" /></label><button type="submit" className="button primary" disabled={!!busy}>Continue task<ArrowRight size={16} aria-hidden="true" /></button></form>}
        <div className="button-row task-actions"><button className="button subtle" disabled={!!busy} onClick={() => { void command('Refresh evidence', () => api.task(task.id)); }}><RefreshCw size={16} aria-hidden="true" />Refresh evidence</button>{task.run_id && <a href={`/studio?run=${encodeURIComponent(task.run_id)}`} className="button subtle">Inspect durable trace<ArrowRight size={16} aria-hidden="true" /></a>}{canContinue && <button className="button primary" disabled={!!busy} onClick={() => { void command('Continue execution', () => api.continueTask(task.id)); }}>Continue execution</button>}</div>
        {task.source_name && <details><summary>Source provenance · {task.source_name}</summary><code className="full-hash">SHA-256 {task.source_sha256}</code></details>}
        </div></section>
        {trace && <ApprovalGateCard key={`${trace.run.id}:${trace.run.active_revision_no}`} run={trace.run} approvals={trace.approvals} busy={!!busy} pauseByDefault={false} onApprove={(body, token) => { void command('Approve quote', async () => { await api.approve(trace.run.id, body, token); return api.task(task.id); }); }} onReject={(body, token) => { void command('Reject quote', async () => { await api.reject(trace.run.id, body, token); return api.task(task.id); }); }} onRevise={raw_request => { void command('Revise quote', async () => { await api.revise(trace.run.id, { raw_request }); return api.task(task.id); }); }} />}
        {result.checks.length > 0 && <section className="panel" aria-labelledby="completion-check-title"><div className="panel-heading"><h2 id="completion-check-title">Record verification</h2><span className="small muted">Read back from persisted state</span></div><ul className="completion-checks">{result.checks.map(check => <li key={check.name}><span className={check.passed ? 'check-passed' : 'check-failed'}>{check.passed ? <Check size={18} aria-hidden="true" /> : <CircleAlert size={18} aria-hidden="true" />}{check.passed ? 'Verified' : 'Not verified'}</span><div><strong>{check.name}</strong><details><summary>Evidence</summary><JsonView value={check.evidence} /></details></div></li>)}</ul></section>}
        <section className="panel" aria-labelledby="observation-title"><div className="panel-heading"><h2 id="observation-title">Actions & observations</h2><span className="small muted">Persisted task memory</span></div><ol className="task-observations">{task.observations.map(observation => <li key={observation.sequence}><span className="observation-index">{observation.sequence}</span><div><h3>{label(observation.action)}</h3><p>{observation.summary}</p><details><summary>Recorded evidence</summary><JsonView value={observation.evidence} /></details></div></li>)}</ol></section>
      </> : <section className="task-empty"><div className="task-loop" aria-hidden="true"><FileText size={24} /><ArrowRight size={18} /><Play size={24} /><ArrowRight size={18} /><ShieldCheck size={24} /></div><h2>From a request to a checked outcome.</h2><p>Start with a quote for Acme. Watch the worker load company context, select approved stock, create a draft, and pause for review.</p><ol><li>Read the goal and any supplied RFQ.</li><li>Check company policy and current inventory.</li><li>Act through the durable runtime and verify the result.</li></ol></section>}
      {recent.length > 0 && <section className="task-history" aria-labelledby="task-history-title"><h2 id="task-history-title">Recent tasks</h2>{recent.map(item => <button key={item.id} disabled={!!busy} onClick={() => { void command('Load task', () => api.task(item.id)); }}><span>{item.goal}</span><StatusBadge status={item.status} /></button>)}</section>}
    </div></div>
    <footer className="studio-footer"><span>Bounded quotation & inventory worker</span><span>Integer INR paise · Explicit approval · Mock business providers</span></footer>
  </main></>;
}

export function CompanyWorkspace() {
  const [company, setCompany] = useState<Awaited<ReturnType<typeof api.company>> | null>(null);
  const [error, setError] = useState('');
  const [filter, setFilter] = useState('');
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => { setBusy(true); try { setCompany(await api.company()); setError(''); } catch (issue) { setError(issue instanceof Error ? issue.message : 'Company records could not be loaded.'); } finally { setBusy(false); } }, []);
  useEffect(() => { void load(); }, [load]);
  return <><WorkspaceHeader active="company" /><main className="worker-shell"><div className="worker-title"><div><h1>Company workspace</h1><p>Inspect the local business records independently of the worker’s explanation.</p></div><button className="button subtle" disabled={busy} onClick={() => { void load(); }}><RefreshCw size={16} aria-hidden="true" />Refresh company records</button></div>{error && <p role="alert" className="error-banner">{error}</p>}{company ? <div className="company-sections"><section className="panel"><div className="panel-heading"><h2>Policies & customer context</h2><span className="mode-label">Sandbox data</span></div><div className="panel-body company-context"><div><h3>Company policy v{String(company.policy.version)}</h3><p>{String(company.policy.notes)}</p><details><summary>Policy snapshot</summary><JsonView value={company.policy} /></details></div><div><h3>Customer directory</h3>{company.customers.map((customer, index) => <p key={index}><strong>{String(customer.name)}</strong><br />{String(customer.email)}</p>)}</div></div></section>
      <section className="panel"><div className="panel-heading"><h2>CRM quotes</h2><span className="small muted">Latest 30 records</span></div><div className="table-scroll" tabIndex={0} aria-label="Company quotes"><table><thead><tr><th>Quote ID</th><th>Customer</th><th>Total</th><th>State</th></tr></thead><tbody>{company.quotes.map(quote => <tr key={quote.quote_id}><td><code title={quote.quote_id}>{shortId(quote.quote_id)}</code></td><td>{quote.customer_email}</td><td>{money(quote.total_amount)}</td><td><StatusBadge status={quote.status} /></td></tr>)}</tbody></table></div>{!company.quotes.length && <p className="empty-inline">No quotes yet. Execute a quotation task to create a draft.</p>}</section>
      <section className="panel"><div className="panel-heading"><h2>Approved catalogue & stock</h2><label className="search-label">Filter catalogue<input type="search" value={filter} onChange={e => setFilter(e.target.value)} placeholder="SKU or category" /></label></div><div className="table-scroll" tabIndex={0} aria-label="Company inventory"><table><thead><tr><th>Product</th><th>Category</th><th>Unit price</th><th>Available</th><th>Reserved</th><th>Fulfilled</th></tr></thead><tbody>{company.stock.filter(row => `${row.sku} ${row.category} ${row.name}`.toLowerCase().includes(filter.toLowerCase())).map(row => <tr key={row.sku}><td><strong>{row.sku}</strong><span className="table-secondary">{row.name}</span></td><td>{row.category}</td><td>{money(row.unit_price)}</td><td>{row.available_qty}</td><td>{row.reserved_qty}</td><td>{row.fulfilled_qty}</td></tr>)}</tbody></table></div></section>
      <section className="panel"><div className="panel-heading"><h2>Mock email dispatches</h2></div><div className="table-scroll" tabIndex={0} aria-label="Company email dispatches"><table><thead><tr><th>Email ID</th><th>Quote</th><th>Recipient</th><th>Approval binding</th></tr></thead><tbody>{company.emails.map(email => <tr key={email.email_id}><td><code>{shortId(email.email_id)}</code></td><td><code>{shortId(email.quote_id)}</code></td><td>{email.recipient}</td><td><code title={email.bound_state_hash}>{shortId(email.bound_state_hash, 12)}</code></td></tr>)}</tbody></table></div>{!company.emails.length && <p className="empty-inline">No emails dispatched. Human approval is required.</p>}</section>
    </div> : !error && <p role="status">Loading company records…</p>}</main></>;
}
