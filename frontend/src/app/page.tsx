import { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowDown, ArrowRight, Check, CircleAlert, GitFork, LoaderCircle, LockKeyhole, RefreshCw, ShieldCheck, Unplug, Workflow, X } from 'lucide-react';
import { api, ApiError } from '../lib/api';
import { shortId } from '../lib/format';
import { focusedStep } from '../lib/execution';
import { useCompactLayout } from '../lib/useCompactLayout';
import type { BenchmarkResponse, CreateRunRequest, RunTraceResponse, StepResponse } from '../types/saga';
import { ScenarioLauncher } from '../components/ScenarioLauncher';
import { RunHeaderBar } from '../components/RunHeaderBar';
import { StepTracePipeline } from '../components/StepTracePipeline';
import { StepInspectorDrawer } from '../components/StepInspectorDrawer';
import { ApprovalGateCard } from '../components/ApprovalGateCard';
import { SandboxForkPanel } from '../components/SandboxForkPanel';
import { ExternalStateTables } from '../components/ExternalStateTables';
import { BenchmarkScorecard } from '../components/BenchmarkScorecard';

const guided = [
  { title: 'Lost CRM response', description: 'Verify the write. Keep one quote.', icon: Unplug },
  { title: 'Worker crash', description: 'Recover persisted in-flight work.', icon: RefreshCw },
  { title: 'Rejection & rollback', description: 'Undo effects, or surface failure.', icon: ShieldCheck },
  { title: 'Stale approval', description: 'Approve, mutate, approve again.', icon: LockKeyhole },
  { title: 'Sandbox fork', description: 'Replay a historical checkpoint.', icon: GitFork },
];
const instructions = [
  'The CRM wrote successfully, but its response was lost. Select step 2, inspect the quote count, then Resume / Reconcile.',
  'The worker crashed after persisting its intent. The 503 response identifies this run; Resume to reconcile the in-flight step.',
  'Reject the quote to roll back CRM and stock in reverse order. Enable “Fail inventory compensation” to demonstrate scenario 3B.',
  'Approve & pause, then Revise RFQ. The old approval becomes stale; the new revision needs a fresh approval.',
  'Choose a revision and a BEFORE_STEP boundary in Sandbox replay. The new run uses isolated records and a fresh approval.',
];

export default function Studio() {
  const [trace, setTrace] = useState<RunTraceResponse | null>(null);
  const [busy, setBusy] = useState('');
  const compact = useCompactLayout();
  const [launcherExpanded, setLauncherExpanded] = useState<boolean | null>(null);
  const lock = useRef(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [notice, setNotice] = useState('');
  const [guide, setGuide] = useState<number | null>(null);
  const [scenario, setScenario] = useState('rfq_01');
  const [openId, setOpenId] = useState('');
  const [recent, setRecent] = useState<string[]>([]);
  const [selected, setSelected] = useState<StepResponse | null>(null);
  const [benchmark, setBenchmark] = useState<BenchmarkResponse | null>(null);
  const [benchmarkError, setBenchmarkError] = useState('');
  const [benchmarkLoading, setBenchmarkLoading] = useState(false);
  const [connection, setConnection] = useState('Checking API');
  const alive = useRef(true);
  const errorBox = useRef<HTMLDivElement>(null);

  const accept = useCallback((next: RunTraceResponse) => {
    if (!alive.current) return;
    setTrace(next); setOpenId(next.run.id); setSelected(null); setConnection('API connected'); setLauncherExpanded(false);
    setRecent(previous => [next.run.id, ...previous.filter(id => id !== next.run.id)].slice(0, 8));
    const url = new URL(window.location.href); url.searchParams.set('run', next.run.id); window.history.replaceState(null, '', url);
  }, []);

  const command = useCallback(async (name: string, action: () => Promise<RunTraceResponse>) => {
    if (lock.current) return;
    lock.current = true; setBusy(name); setError(null); setNotice('');
    try { accept(await action()); setNotice(`${name} finished. Trace is up to date.`); }
    catch (cause) {
      const issue = cause instanceof ApiError ? cause : new ApiError(0, 'UNEXPECTED_ERROR', 'The action could not finish. Reload the trace before retrying.');
      if (issue.status === 503 && issue.runId) {
        try { accept(await api.trace(issue.runId)); setNotice('Worker crash captured. The durable trace is loaded; use Resume run to recover.'); }
        catch { setOpenId(issue.runId); setError(new ApiError(503, issue.code, `Worker crashed in run ${issue.runId}. Trace loading failed; use Open run to fetch it.`, issue.details)); }
      } else { setError(issue); if (issue.status === 0) setConnection('API unreachable'); }
    } finally { lock.current = false; if (alive.current) setBusy(''); }
  }, [accept]);

  const loadBenchmarks = useCallback(async () => {
    setBenchmarkLoading(true);
    try { const data = await api.benchmarks(); if (alive.current) { setBenchmark(data); setBenchmarkError(''); setConnection('API connected'); } }
    catch (cause) { if (alive.current) { setBenchmarkError(cause instanceof Error ? cause.message : 'Could not load benchmarks.'); setConnection(cause instanceof ApiError && cause.status > 0 ? 'API connected' : 'API unreachable'); } }
    finally { if (alive.current) setBenchmarkLoading(false); }
  }, []);

  useEffect(() => { alive.current = true; void loadBenchmarks(); return () => { alive.current = false; }; }, [loadBenchmarks]);
  useEffect(() => {
    const runId = new URL(window.location.href).searchParams.get('run');
    if (runId) void command('Load run', () => api.trace(runId));
  }, [command]);
  useEffect(() => { if (error) errorBox.current?.focus(); }, [error]);

  function startGuide(index: number) {
    setGuide(index);
    if (index === 4 && trace) { document.getElementById('sandbox-fork')?.scrollIntoView({ behavior: 'smooth', block: 'center' }); return; }
    const chaos = index === 0 ? { drop_response_after_write_on_step: 2 } : index === 1 ? { crash_worker_after_step_in_flight: 1 } : {};
    void command('Guided scenario', () => api.scenario(scenario, chaos));
  }

  function launch(request: CreateRunRequest) { setGuide(null); void command('Create run', () => api.create(request)); }
  const focus = trace ? focusedStep(trace) : undefined;
  const waitingForReview = !!trace && trace.run.status === 'AWAITING_APPROVAL' && trace.approvals.some(item => item.revision_no === trace.run.active_revision_no && item.status === 'PENDING');
  return <>
    <a href="#studio-workspace" className="skip-link">Skip to execution workspace</a>
    <header className="app-header"><a className="brand" href="/" aria-label="SagaAgent studio home"><span className="brand-mark"><Workflow size={21} aria-hidden="true" /></span><strong>SagaAgent</strong><span className="brand-divider" /><span className="brand-context">Durable execution runtime</span></a><div className="header-right"><span className={`connection ${connection === 'API connected' ? 'online' : ''}`}><span className="status-dot" aria-hidden="true" />{connection}</span><span className="environment-label">LOCAL STUDIO</span></div></header>
    <main className="studio-shell"><div className="studio-title"><div><h1>Trace & Chaos Studio</h1><p>Break a workflow. Inspect the evidence. Recover with confidence.</p></div><form className="open-run" onSubmit={event => { event.preventDefault(); setGuide(null); void command('Load run', () => api.trace(openId.trim())); }}><label className="sr-only" htmlFor="run-id">Existing run ID</label><input id="run-id" value={openId} onChange={event => setOpenId(event.target.value)} placeholder="Open an existing run ID" required /><button className="button subtle" disabled={!!busy} type="submit">Open run<ArrowRight size={14} aria-hidden="true" /></button></form></div>
      <section className="walkthroughs" aria-label="Guided fault scenarios">{guided.map((item, index) => <button key={item.title} disabled={!!busy} aria-pressed={guide === index} className={`walkthrough ${guide === index ? 'selected' : ''}`} onClick={() => startGuide(index)} aria-label={`Run guided scenario ${index + 1}: ${item.title}`}><span className="walkthrough-number">{index + 1}</span><span><strong>{item.title}</strong><span className="small">{item.description}</span></span><item.icon size={17} aria-hidden="true" /></button>)}</section>
      {guide !== null && <div className="guided-instruction"><ShieldCheck size={17} aria-hidden="true" /><p><strong>Scenario {guide + 1}.</strong> {instructions[guide]}</p></div>}
      <div className="feedback-area" aria-live="polite">{busy && <div className="progress-message"><LoaderCircle className="spin" size={16} aria-hidden="true" />{busy} in progress…</div>}{!busy && notice && <div className="notice"><Check size={16} aria-hidden="true" />{notice}</div>}</div>
      {error && <div className="error-banner" role="alert" ref={errorBox} tabIndex={-1}><CircleAlert size={19} aria-hidden="true" /><div><strong>{error.status ? `HTTP ${error.status} · ` : ''}{error.code}</strong><p>{error.message}</p>{error.details.length > 0 && <details><summary>Server details</summary><pre>{JSON.stringify(error.details, null, 2)}</pre></details>}</div><button className="icon-button" aria-label="Dismiss error" onClick={() => setError(null)}><X size={18} aria-hidden="true" /></button></div>}
      <div className="workspace" id="studio-workspace"><div className="workspace-sidebar"><ScenarioLauncher busy={!!busy} expanded={!compact || (launcherExpanded ?? !trace)} onExpandedChange={setLauncherExpanded} onLaunch={launch} onScenarioSelect={setScenario} />{recent.length > 0 && <nav className="recent-runs" aria-label="Recent runs"><h3>This session</h3>{recent.map(id => <button key={id} className={trace?.run.id === id ? 'active' : ''} disabled={!!busy} onClick={() => { setGuide(null); void command('Load run', () => api.trace(id)); }}><Workflow size={13} aria-hidden="true" /><span className="mono">{shortId(id, 12)}</span><ArrowRight size={12} aria-hidden="true" /></button>)}</nav>}</div>
        <div className="workspace-main">{trace ? <>
          <RunHeaderBar run={trace.run} busy={!!busy} waitingForReview={waitingForReview} onInspectFocus={focus ? () => setSelected(focus) : undefined} onResume={() => { void command('Resume run', () => api.resume(trace.run.id)); }} onRefresh={() => { void command('Refresh trace', () => api.trace(trace.run.id)); }} onParent={id => { setGuide(null); void command('Load parent', () => api.trace(id)); }} />
          <StepTracePipeline steps={trace.steps} revisions={trace.revisions} activeRevision={trace.run.active_revision_no} focusedStepId={focus?.id} waitingForReview={waitingForReview} onInspect={setSelected} />
          <div className="decision-grid"><ApprovalGateCard key={`${trace.run.id}:${trace.run.active_revision_no}:${guide}`} run={trace.run} approvals={trace.approvals} busy={!!busy} pauseByDefault={guide === 3} onApprove={(body, token) => { void command('Approval', () => api.approve(trace.run.id, body, token)); }} onReject={(body, token) => { void command('Rejection', () => api.reject(trace.run.id, body, token)); }} onRevise={raw_request => { void command('Revise RFQ', () => api.revise(trace.run.id, { raw_request })); }} /><SandboxForkPanel key={`${trace.run.id}:${trace.run.active_revision_no}`} trace={trace} busy={!!busy} onFork={body => { void command('Sandbox fork', () => api.fork(trace.run.id, body)); }} /></div>
          <ExternalStateTables records={trace.external_records} namespace={trace.run.sandbox_namespace} />
        </> : <section className="empty-workspace panel"><div className="empty-pipeline" aria-hidden="true"><span><Workflow size={21} /></span><ArrowRight size={19} /><span><ShieldCheck size={21} /></span><ArrowRight size={19} /><span><Check size={21} /></span></div><h2>A clear view of every side effect.</h2><p>Launch an RFQ or choose a guided scenario. Follow each step from durable intent to verified outcome.</p><div className="empty-instruction"><ArrowDown size={16} aria-hidden="true" /><span>Start with “Lost CRM response” to see reconciliation in action.</span></div><dl className="empty-facts"><div><dt>6</dt><dd>durable steps</dd></div><div><dt>5</dt><dd>fault scenarios</dd></div><div><dt>1</dt><dd>auditable trace</dd></div></dl></section>}
          <BenchmarkScorecard data={benchmark} error={benchmarkError} loading={benchmarkLoading} onRetry={() => { void loadBenchmarks(); }} />
        </div></div>
      <footer className="studio-footer"><span>SagaAgent · SQLite reference harness</span><span>Mock services · INR amounts converted from paise · {api.baseUrl || 'Local /api proxy'}</span></footer>
    </main><StepInspectorDrawer step={selected} attempts={trace?.attempts ?? []} onClose={() => setSelected(null)} />
  </>;
}
