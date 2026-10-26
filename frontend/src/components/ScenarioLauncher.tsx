import { ChevronDown, FlaskConical, Play, SlidersHorizontal } from 'lucide-react';
import { useState } from 'react';
import scenarios from '../data/rfq_scenarios.json';
import type { ChaosConfig, CreateRunRequest } from '../types/saga';

interface Props { busy: boolean; expanded: boolean; onExpandedChange: (expanded: boolean) => void; onLaunch: (request: CreateRunRequest) => void; onScenarioSelect: (id: string) => void; }
const numericFaults: { key: keyof ChaosConfig; name: string; max: number }[] = [
  { key: 'drop_response_after_write_on_step', name: 'Lose write response', max: 5 },
  { key: 'crash_worker_after_step_in_flight', name: 'Crash before effect', max: 5 },
  { key: 'crash_after_external_commit_on_step', name: 'Crash after effect', max: 5 },
  { key: 'transient_timeout_before_write_on_step', name: 'Timeout before write', max: 5 },
  { key: 'fail_compensation_on_step', name: 'Fail compensation', max: 2 },
  { key: 'crash_after_compensation_write_on_step', name: 'Crash after compensation', max: 2 },
  { key: 'drop_compensation_response_on_step', name: 'Lose compensation response', max: 2 },
];

export function ScenarioLauncher({ busy, expanded, onExpandedChange, onLaunch, onScenarioSelect }: Props) {
  const first = scenarios[0];
  const [scenario, setScenario] = useState(first.scenario_id);
  const [name, setName] = useState(first.customer_name);
  const [email, setEmail] = useState(first.customer_email);
  const [raw, setRaw] = useState(first.raw_request);
  const [chaos, setChaos] = useState<ChaosConfig>({});
  return <aside className="launcher panel" aria-labelledby="launcher-title">
    <div className="panel-heading"><h2 id="launcher-title"><FlaskConical size={18} aria-hidden="true" /> New execution</h2><button className="icon-button launcher-toggle" type="button" aria-label={expanded ? 'Collapse new execution form' : 'Expand new execution form'} aria-expanded={expanded} aria-controls="launcher-fields" onClick={() => onExpandedChange(!expanded)}><ChevronDown size={19} aria-hidden="true" /></button></div>
    <div id="launcher-fields" hidden={!expanded}>
    <form className="form-stack" onSubmit={event => { event.preventDefault(); onLaunch({ scenario_id: scenario, customer_name: name, customer_email: email, raw_request: raw, chaos_config: chaos }); }}>
      <label>RFQ preset<select value={scenario} onChange={event => {
        const next = scenarios.find(item => item.scenario_id === event.target.value);
        if (next) { setScenario(next.scenario_id); setName(next.customer_name); setEmail(next.customer_email); setRaw(next.raw_request); onScenarioSelect(next.scenario_id); }
      }}>{scenarios.map(item => <option key={item.scenario_id} value={item.scenario_id}>{item.scenario_id.replace('rfq_', 'RFQ ')} · {item.customer_name}</option>)}</select></label>
      <label>Customer name<input required maxLength={200} value={name} onChange={e => setName(e.target.value)} /></label>
      <label>Customer email<input type="email" required maxLength={320} value={email} onChange={e => setEmail(e.target.value)} /></label>
      <label>Requested items<textarea required maxLength={20000} value={raw} onChange={e => setRaw(e.target.value)} rows={3} aria-describedby="rfq-hint" /></label>
      <p className="field-hint" id="rfq-hint">Use explicit SKU lines, for example <code>10 x APL-001, 2 x APL-002</code>.</p>
      <details className="fault-config"><summary><SlidersHorizontal size={15} aria-hidden="true" /> Fault injection <span className="muted">{Object.values(chaos).filter(Boolean).length} active</span></summary>
        <div className="form-stack">
          {numericFaults.map(fault => <label key={fault.key}>{fault.name}<select value={typeof chaos[fault.key] === 'number' ? String(chaos[fault.key]) : ''} onChange={e => setChaos({ ...chaos, [fault.key]: e.target.value ? Number(e.target.value) : null })}><option value="">Off</option>{Array.from({ length: fault.max }, (_, i) => <option key={i + 1} value={i + 1}>Step {i + 1}</option>)}</select></label>)}
          {([{ key: 'crash_after_dispatch_claim', name: 'Crash after dispatch claim' }, { key: 'keep_verification_unknown', name: 'Keep verification unknown' }, { key: 'fail_finalization_once', name: 'Fail finalization once' }] as const).map(fault => <label className="check-label" key={fault.key}><input type="checkbox" checked={chaos[fault.key] ?? false} onChange={e => setChaos({ ...chaos, [fault.key]: e.target.checked })} />{fault.name}</label>)}
          <button type="button" className="text-button" onClick={() => setChaos({})}>Clear faults</button>
        </div>
      </details>
      <button type="submit" className="button primary full" disabled={busy}><Play size={15} aria-hidden="true" /> Create run</button>
    </form>
    <div className="launcher-note"><span className="status-dot" aria-hidden="true" /><p>Durable state. Explicit approval.<br />All external services are mocked.</p></div>
    <details className="catalogue-note"><summary>Available catalogue</summary><p className="small muted">APL-001 through APL-030. Laptops, monitors, keyboards, docks and headsets. Prices are calculated by the backend.</p></details>
    </div>
  </aside>;
}
