import { Workflow } from 'lucide-react';

export function WorkspaceHeader({ active }: { active: 'task' | 'company' }) {
  return <header className="app-header worker-header"><a className="brand" href="/"><span className="brand-mark"><Workflow size={21} aria-hidden="true" /></span><strong>SagaAgent</strong></a><nav className="workspace-nav" aria-label="Workspaces"><a href="/" aria-current={active === 'task' ? 'page' : undefined}>Task worker</a><a href="/company" aria-current={active === 'company' ? 'page' : undefined}>Company workspace</a><a href="/studio">Chaos studio</a></nav></header>;
}
