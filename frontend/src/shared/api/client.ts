import type { paths } from './generated/openapi';

const API_BASE = '/api/v1';

export type RuntimeStatus =
  paths['/api/v1/runtime']['get']['responses']['200']['content']['application/json'];

export async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { Accept: 'application/json' },
    signal,
  });

  if (!response.ok) {
    throw new Error(`GET ${path} failed with status ${response.status}`);
  }

  return (await response.json()) as T;
}
