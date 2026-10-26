import { Database, ExternalLink } from 'lucide-react';
import { useState } from 'react';
import type { ExternalRecords } from '../types/saga';
import { dateTime, isRecord, money, shortId } from '../lib/format';
import { JsonView, StatusBadge } from './shared';

type Tab = 'stock' | 'holds' | 'quotes' | 'emails';
const titles: Record<Tab, string> = { stock: 'Stock', holds: 'Holds', quotes: 'Quotes', emails: 'Dispatched emails' };

export function ExternalStateTables({ records, namespace }: { records: ExternalRecords; namespace: string }) {
  const [tab, setTab] = useState<Tab>('stock');
  const [filter, setFilter] = useState('');
  const stock = records.stock.filter(row => `${row.sku} ${row.name}`.toLowerCase().includes(filter.toLowerCase()));
  return <section className="panel external-panel" aria-labelledby="external-title"><div className="panel-heading"><h2 id="external-title"><Database size={17} aria-hidden="true" /> External service state</h2><code className="namespace" title={namespace}>{namespace === 'live' ? 'namespace: live' : `sandbox: ${shortId(namespace.slice(8))}`}</code></div>
    <div className="resource-tabs" role="tablist" aria-label="External services">{(Object.keys(titles) as Tab[]).map(key => <button type="button" role="tab" id={`tab-${key}`} aria-controls="external-tab-panel" aria-selected={tab === key} tabIndex={tab === key ? 0 : -1} key={key} className={tab === key ? 'active' : ''} onClick={() => setTab(key)} onKeyDown={event => {
      const keys = Object.keys(titles) as Tab[];
      let next = keys.indexOf(key);
      if (event.key === 'ArrowRight') next = (next + 1) % keys.length;
      else if (event.key === 'ArrowLeft') next = (next + keys.length - 1) % keys.length;
      else if (event.key === 'Home') next = 0;
      else if (event.key === 'End') next = keys.length - 1;
      else return;
      event.preventDefault(); setTab(keys[next]); document.getElementById(`tab-${keys[next]}`)?.focus();
    }}>{titles[key]}<span>{records[key].length}</span></button>)}</div>
    <div role="tabpanel" id="external-tab-panel" aria-labelledby={`tab-${tab}`}>
      {tab === 'stock' && <div className="table-toolbar"><label className="search-label">Filter stock<input type="search" value={filter} onChange={e => setFilter(e.target.value)} placeholder="SKU or product name" /></label><span className="small muted">Available / reserved / fulfilled</span></div>}
      <div className="table-scroll" tabIndex={0} aria-label={`${titles[tab]} table`}>
        {tab === 'stock' && <table><caption className="sr-only">Current namespace stock; prices shown in rupees from integer paise</caption><thead><tr><th>SKU / product</th><th>Unit price</th><th className="numeric">Available</th><th className="numeric">Reserved</th><th className="numeric">Fulfilled</th></tr></thead><tbody>{stock.map(row => <tr key={row.sku}><td><strong className="mono">{row.sku}</strong><span className="table-secondary">{row.name}</span></td><td title={`${row.unit_price} paise`}>{money(row.unit_price)}</td><td className="numeric">{row.available_qty}</td><td className="numeric">{row.reserved_qty}</td><td className="numeric">{row.fulfilled_qty}</td></tr>)}</tbody></table>}
        {tab === 'holds' && <table><caption className="sr-only">Inventory holds for this execution</caption><thead><tr><th>Hold ID</th><th>Items</th><th>State</th><th>Created</th></tr></thead><tbody>{records.holds.map(row => <tr key={row.hold_id}><td className="mono" title={row.hold_id}>{shortId(row.hold_id)}<details><summary>Full IDs</summary><JsonView value={{ hold_id: row.hold_id, operation_id: row.operation_id, released_by_op_id: row.released_by_op_id }} /></details></td><td>{row.items.filter(isRecord).map((item, i) => <span className="table-secondary" key={i}>{String(item.qty)} × {String(item.sku)}</span>)}</td><td><StatusBadge status={row.status} /></td><td>{dateTime(row.created_at)}</td></tr>)}</tbody></table>}
        {tab === 'quotes' && <table><caption className="sr-only">CRM quotes for this execution</caption><thead><tr><th>Quote ID</th><th>Customer</th><th>Total</th><th>State</th></tr></thead><tbody>{records.quotes.map(row => <tr key={row.quote_id}><td className="mono" title={row.quote_id}>{shortId(row.quote_id)}<details><summary>Quote payload</summary><JsonView value={row} /></details></td><td>{row.customer_email}</td><td title={`${row.total_amount} paise`}>{money(row.total_amount)}</td><td><StatusBadge status={row.status} /></td></tr>)}</tbody></table>}
        {tab === 'emails' && <table><caption className="sr-only">Mock dispatched emails for this execution</caption><thead><tr><th>Email / quote</th><th>Recipient</th><th>Sent</th><th>Payload</th></tr></thead><tbody>{records.emails.map(row => <tr key={row.email_id}><td className="mono" title={row.email_id}>{shortId(row.email_id)}<span className="table-secondary" title={row.quote_id}>Quote {shortId(row.quote_id)}</span></td><td>{row.recipient}</td><td>{dateTime(row.sent_at)}</td><td><details><summary><ExternalLink size={12} aria-hidden="true" /> View dispatch</summary><JsonView value={row} /></details></td></tr>)}</tbody></table>}
      </div>
      {records[tab].length === 0 && <p className="empty-inline">No {titles[tab].toLowerCase()} recorded for this execution.</p>}
      {tab === 'stock' && stock.length === 0 && records.stock.length > 0 && <p className="empty-inline">No products match “{filter}”.</p>}
    </div>
  </section>;
}
