import { spawn } from 'node:child_process';
import { mkdir, mkdtemp, writeFile } from 'node:fs/promises';
import { createServer } from 'node:net';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium, expect } from '@playwright/test';

const frontend = fileURLToPath(new URL('../', import.meta.url));
const root = path.resolve(frontend, '..');
const backend = path.join(root, 'backend');
const python = process.env.SAGA_TEST_PYTHON || path.join(root, '.venv', ...(process.platform === 'win32' ? ['Scripts', 'python.exe'] : ['bin', 'python']));
const vite = path.join(frontend, 'node_modules', 'vite', 'bin', 'vite.js');
const results = path.join(frontend, 'test-results');
const processLogs = [];
const children = [];

async function freePort() {
  return new Promise((resolve, reject) => {
    const server = createServer();
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => { const address = server.address(); server.close(() => resolve(address.port)); });
  });
}

function launch(executable, args, options) {
  const child = spawn(executable, args, { ...options, stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true });
  children.push(child);
  child.stdout.on('data', value => processLogs.push(String(value)));
  child.stderr.on('data', value => processLogs.push(String(value)));
  return child;
}

async function ready(url, child) {
  const deadline = Date.now() + 30000;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) throw new Error(`Service exited with ${child.exitCode}`);
    try { const response = await fetch(url); if (response.ok) return; } catch { /* startup pending */ }
    await new Promise(resolve => setTimeout(resolve, 250));
  }
  throw new Error(`Service did not start: ${url}`);
}

async function run() {
  await mkdir(results, { recursive: true });
  const dir = await mkdtemp(path.join(results, 'integration-'));
  const backendPort = await freePort();
  const appUrl = 'http://127.0.0.1:3000';
  const apiUrl = `http://127.0.0.1:${backendPort}`;
  const dbPath = path.join(dir, 'studio.db').replaceAll('\\', '/');
  const backendProcess = launch(python, ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', String(backendPort)], { cwd: backend, env: { ...process.env, SAGA_DATABASE_URL: `sqlite+aiosqlite:///${dbPath}`, SAGA_HMAC_SECRET: 'phase-five-integration-test-secret-32-chars', SAGA_REVIEWER_TOKENS: '{"local-reviewer-token":"sales_mgr_01"}' } });
  await ready(`${apiUrl}/openapi.json`, backendProcess);
  const frontendProcess = launch(process.execPath, [vite, '--host', '127.0.0.1', '--port', '3000', '--strictPort'], { cwd: frontend, env: { ...process.env, VITE_API_BASE_URL: apiUrl } });
  await ready(appUrl, frontendProcess);

  const browser = await chromium.launch({ headless: true });
  let assertions = 0;
  const step = async (name, callback) => { await callback(); assertions += 1; console.log(`PASS ${String(assertions).padStart(2, '0')} ${name}`); };
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, reducedMotion: 'reduce' });
    const pageErrors = [];
    page.on('pageerror', error => pageErrors.push(error.message));
    const launchGuided = async index => {
      const before = new URL(page.url()).searchParams.get('run');
      await page.getByRole('button', { name: new RegExp(`Run guided scenario ${index}:`) }).click();
      await expect.poll(() => new URL(page.url()).searchParams.get('run')).not.toBe(before);
    };
    await page.goto(appUrl);
    await step('studio and persisted benchmark render', async () => {
      await expect(page.getByRole('heading', { name: 'Trace & Chaos Studio' })).toBeVisible();
      await expect(page.getByRole('heading', { name: 'Fault-injection benchmark' })).toBeVisible();
      await expect(page.getByText('200 total executions')).toBeVisible();
    });

    await launchGuided(1);
    await step('lost CRM response enters reconciliation', async () => {
      await expect(page.getByRole('button', { name: /Resume \/ Reconcile/ })).toBeVisible();
      await expect(page.locator('[aria-current="step"]')).toContainText('Draft quote');
      await page.getByRole('button', { name: /Inspect revision 1 step 2/ }).click();
      await expect(page.getByRole('dialog').getByTitle('OUTCOME_UNKNOWN')).toBeVisible();
      await page.getByRole('button', { name: 'Close step inspector' }).click();
    });
    await page.evaluate(() => globalThis.scrollTo(0, 0));
    await page.screenshot({ path: path.join(dir, 'uncertain.png'), fullPage: true });
    await page.getByRole('button', { name: /Resume \/ Reconcile/ }).click();
    await step('reconciliation verifies one quote', async () => {
      await expect(page.getByText('Awaiting approval').first()).toBeVisible();
      await page.getByRole('tab', { name: /Quotes/ }).click();
      await expect(page.locator('#external-tab-panel tbody tr')).toHaveCount(1);
      await page.getByRole('button', { name: /Inspect revision 1 step 2/ }).click();
      await expect(page.getByRole('dialog').getByText('APPLIED').first()).toBeVisible();
      await page.getByRole('button', { name: 'Close step inspector' }).click();
      await expect(page.locator('[aria-current="step"]')).toContainText('Approval gate');
      await expect(page.getByText('Reconciled', { exact: true })).toBeVisible();
    });
    await step('review shortcut moves keyboard focus to the approval panel', async () => {
      await page.getByRole('button', { name: 'Review quote', exact: true }).click();
      await expect(page.locator('#human-approval')).toBeFocused();
    });
    await page.evaluate(() => globalThis.scrollTo(0, 0));
    await page.screenshot({ path: path.join(dir, 'desktop.png'), fullPage: true });
    await page.screenshot({ path: path.join(dir, 'desktop-viewport.png') });

    await launchGuided(2);
    await step('503 recovers its run ID and loads the trace', async () => {
      await expect(page.getByText('Worker crash captured.')).toBeVisible();
      await expect(page.getByRole('button', { name: 'Resume run' })).toBeEnabled();
      const runId = new URL(page.url()).searchParams.get('run');
      if (!runId) throw new Error('Crash response did not yield a run ID');
      const response = await fetch(`${apiUrl}/api/runs/${runId}/trace`);
      const trace = await response.json();
      if (trace.steps[1].status !== 'IN_FLIGHT') throw new Error('Expected durable in-flight reservation');
    });
    await page.getByRole('button', { name: 'Resume run' }).click();
    await expect(page.getByText('Awaiting approval').first()).toBeVisible();

    await launchGuided(3);
    await expect(page.getByText('Awaiting approval').first()).toBeVisible();
    await page.getByRole('button', { name: 'Reject & roll back' }).click();
    await step('rejection compensates and closes the run', async () => {
      await expect(page.getByText('Compensated halted').first()).toBeVisible();
      await page.getByRole('tab', { name: /Holds/ }).click();
      await expect(page.getByRole('row').filter({ hasText: 'Released' })).toHaveCount(1);
    });
    await launchGuided(3);
    await expect(page.getByText('Awaiting approval').first()).toBeVisible();
    await page.getByLabel('Fail inventory compensation (scenario 3B)').check();
    await page.getByRole('button', { name: 'Reject & roll back' }).click();
    await step('failed compensation identifies the outstanding hold', async () => {
      await expect(page.getByText('Failed needs human').first()).toBeVisible();
      await expect(page.getByText(/COMPENSATION_FAILED: uncompensated/)).toBeVisible();
      await page.getByRole('button', { name: 'Inspect affected step' }).click();
      await expect(page.getByRole('dialog').getByText('Compensation failed').first()).toBeVisible();
      await page.getByRole('button', { name: 'Close step inspector' }).click();
    });

    await launchGuided(4);
    await expect(page.getByText('Awaiting approval').first()).toBeVisible();
    await page.getByRole('button', { name: 'Approve & pause' }).click();
    await step('payload-bound approval pauses before dispatch', async () => {
      await expect(page.getByText('Approval recorded.')).toBeVisible();
      await expect(page.locator('[aria-current="step"]')).toContainText('Send email');
      await page.getByRole('tab', { name: /Dispatched emails/ }).click();
      await expect(page.getByText('No dispatched emails recorded')).toBeVisible();
    });
    await page.getByRole('button', { name: 'Revise RFQ' }).click();
    await step('revision invalidates the old approval', async () => {
      await expect(page.getByText('Revision 2').first()).toBeVisible();
      await page.getByText('Approval history').click();
      await expect(page.getByText('Invalidated stale')).toBeVisible();
    });
    await page.getByLabel('Pause after approval, before dispatch').uncheck();
    await page.getByRole('button', { name: 'Approve & dispatch' }).click();
    await step('fresh approval dispatches the revised quote', async () => {
      await expect(page.getByText('Completed').first()).toBeVisible();
      await expect(page.locator('[aria-current="step"]')).toHaveCount(0);
      await page.getByRole('tab', { name: /Dispatched emails/ }).click();
      await expect(page.locator('#external-tab-panel tbody tr')).toHaveCount(1);
    });
    const parentId = new URL(page.url()).searchParams.get('run');

    await page.getByRole('button', { name: /Run guided scenario 5:/ }).click();
    await expect(page.getByLabel('Revision').last()).toHaveValue('2');
    await page.getByLabel('Before step').selectOption('2');
    await page.getByRole('button', { name: 'Fork to sandbox' }).click();
    await step('historical fork switches to an isolated namespace', async () => {
      await expect(page.getByText('SANDBOX', { exact: true })).toBeVisible();
      await expect(page.getByText('Awaiting approval').first()).toBeVisible();
      await page.getByText('Namespace & source record map').click();
      await expect(page.getByText(/sandbox_/).first()).toBeVisible();
      const childId = new URL(page.url()).searchParams.get('run');
      if (!childId || childId === parentId) throw new Error('Fork did not switch to a child run');
      const child = await (await fetch(`${apiUrl}/api/runs/${childId}/trace`)).json();
      const parent = await (await fetch(`${apiUrl}/api/runs/${parentId}/trace`)).json();
      if (child.run.execution_mode !== 'SANDBOX' || parent.run.status !== 'COMPLETED') throw new Error('Live/sandbox isolation was not preserved');
      if (child.run.agent_plan.line_items[0].qty !== parent.run.agent_plan.line_items[0].qty) throw new Error('Fork did not select the active revision');
    });

    await page.setViewportSize({ width: 375, height: 812 });
    await step('mobile viewport has no page-level horizontal overflow', async () => {
      await expect(page.getByRole('heading', { name: 'Trace & Chaos Studio' })).toBeVisible();
      const overflow = await page.evaluate(() => globalThis.document.documentElement.scrollWidth > globalThis.innerWidth + 1);
      if (overflow) throw new Error('Page overflows at 375px');
      await expect.poll(() => page.locator('.walkthrough[aria-pressed="true"]').evaluate(button => { const bounds = button.getBoundingClientRect(); const strip = button.parentElement.getBoundingClientRect(); return bounds.left >= strip.left - 1 && bounds.right <= strip.right + 1; })).toBe(true);
    });
    await step('mobile launcher collapses and preserves entered values when reopened', async () => {
      await expect(page.locator('#launcher-fields')).toBeHidden();
      await page.getByRole('button', { name: 'Expand new execution form' }).click();
      await page.getByLabel('Customer name', { exact: true }).fill('Preserved mobile input');
      await page.getByRole('button', { name: 'Collapse new execution form' }).click();
      await expect(page.locator('#launcher-fields')).toBeHidden();
      await page.getByRole('button', { name: 'Expand new execution form' }).click();
      await expect(page.getByLabel('Customer name', { exact: true })).toHaveValue('Preserved mobile input');
      await page.getByRole('button', { name: 'Collapse new execution form' }).click();
    });
    await step('mobile trace is vertical and review is directly reachable', async () => {
      const nodes = page.locator('.step-node');
      const first = await nodes.nth(0).boundingBox();
      const second = await nodes.nth(1).boundingBox();
      if (!first || !second || Math.abs(first.x - second.x) > 1 || second.y < first.y + first.height) throw new Error('Expected vertically connected steps');
      await page.getByRole('button', { name: 'Review quote', exact: true }).click();
      await expect(page.locator('#human-approval')).toBeFocused();
    });
    await page.evaluate(() => globalThis.scrollTo(0, 0));
    await expect.poll(() => page.locator('.walkthrough[aria-pressed="true"]').evaluate(button => { const bounds = button.getBoundingClientRect(); const strip = button.parentElement.getBoundingClientRect(); return bounds.left >= strip.left - 1 && bounds.right <= strip.right + 1; })).toBe(true);
    await page.screenshot({ path: path.join(dir, 'mobile.png'), fullPage: true });
    await page.screenshot({ path: path.join(dir, 'mobile-viewport.png') });
    await page.locator('.trace-panel').screenshot({ path: path.join(dir, 'mobile-trace.png') });
    await step('layout remains contained at 320, 768 and 1024 pixels', async () => {
      for (const width of [320, 768, 1024]) {
        await page.setViewportSize({ width, height: 900 });
        await expect.poll(() => page.evaluate(() => globalThis.document.documentElement.scrollWidth <= globalThis.innerWidth + 1)).toBe(true);
        if (width === 768) { await page.evaluate(() => globalThis.scrollTo(0, 0)); await page.screenshot({ path: path.join(dir, 'tablet.png'), fullPage: true }); }
      }
      await page.setViewportSize({ width: 375, height: 812 });
    });

    await launchGuided(3);
    await expect(page.getByText('Awaiting approval').first()).toBeVisible();
    await page.getByLabel('Reviewer profile').selectOption('invalid-token');
    await page.getByRole('button', { name: 'Reject & roll back' }).click();
    await step('authentication failure is shown without losing the trace', async () => {
      await expect(page.getByText(/INVALID_CREDENTIALS/)).toBeVisible();
      await expect(page.getByText('Awaiting approval').first()).toBeVisible();
    });
    if (pageErrors.length) throw new Error(`Browser errors: ${pageErrors.join('; ')}`);
    await writeFile(path.join(dir, 'results.json'), JSON.stringify({ assertions, apiUrl, appUrl, screenshots: ['desktop.png', 'desktop-viewport.png', 'mobile.png', 'mobile-viewport.png', 'mobile-trace.png', 'tablet.png', 'uncertain.png'] }, null, 2));
    console.log(`Integration: ${assertions} scenarios and interaction checks passed. Evidence: ${dir}`);
  } finally { await browser.close(); }
}

try { await run(); }
catch (error) { console.error(error); console.error(processLogs.slice(-30).join('')); process.exitCode = 1; }
finally { for (const child of children.reverse()) { if (child.exitCode === null) child.kill(); } }
