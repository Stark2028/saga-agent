export const money = (paise: number): string =>
  Number.isSafeInteger(paise) ? (paise / 100).toLocaleString('en-IN', { style: 'currency', currency: 'INR' }) : '—';
export const shortId = (value: string, length = 8): string => value ? value.slice(0, length) : '—';
export const shortHash = (value: string): string => value ? `${value.slice(0, 10)}…${value.slice(-6)}` : 'Not bound yet';
export const label = (value: string): string => value.toLowerCase().replaceAll('_', ' ').replace(/^\w/, char => char.toUpperCase());
export const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null && !Array.isArray(value);
export const integer = (value: unknown): number | null => typeof value === 'number' && Number.isSafeInteger(value) ? value : null;
export const dateTime = (value: string | null): string => value ? new Date(value).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'medium' }) : '—';
