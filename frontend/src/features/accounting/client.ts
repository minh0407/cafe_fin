import { api } from '../../shared/api';
export const requestKey = () => crypto.randomUUID();
const encode = (value: string) => encodeURIComponent(value).replace(/[!'()*~.]/g, char => `%${char.charCodeAt(0).toString(16).toUpperCase()}`);
export function query(params: Record<string, string | number | undefined>) {
  return Object.entries(params).filter(([, value]) => value !== undefined && value !== '').map(([key, value]) => `${key}=${encode(String(value))}`).join('&');
}
export const get = <T,>(path: string, signal?: AbortSignal) => api<T>(`/accounting${path}`, { signal });
export const write = <T,>(path: string, body: object, method = 'POST') => api<T>(`/accounting${path}`, { method, body: JSON.stringify(body) });
export async function downloadFile(fileId: string, filename: string) {
  const blob = await api<Blob>(`/files/${encodeURIComponent(fileId)}/content`, {}, true, 'blob');
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a'); link.href = url; link.download = filename;
  link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}
