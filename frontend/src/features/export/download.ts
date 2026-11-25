import { API_BASE } from '@/shared/api/client';
import { mockMediaUrl } from '@/shared/api/mock/media';

export type SavedFile = 'mp4' | 'srt';

/** The last file a save button started; the token tells two saves of the same kind apart. */
let saved: { kind: SavedFile; token: number } | null = null;
const listeners = new Set<() => void>();

export function subscribeSaved(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function readSaved(): { kind: SavedFile; token: number } | null {
  return saved;
}

/** Starts a file download without leaving the page, and tells the save notice which file went. */
export function startDownload(href: string): void {
  const match = /\/download\/(mp4|srt)$/u.exec(href)?.[1];
  const kind = match === 'mp4' || match === 'srt' ? match : undefined;
  const mockKind =
    import.meta.env.VITE_API_MODE === 'mock' && href.startsWith(`${API_BASE}/videos/`) ? kind : undefined;

  const link = document.createElement('a');
  link.href = mockKind === undefined ? href : mockMediaUrl(mockKind);
  link.download = mockKind === undefined ? '' : `example.${mockKind}`;
  link.rel = 'noopener';
  link.hidden = true;
  document.body.append(link);
  link.click();
  link.remove();

  if (kind !== undefined) {
    saved = { kind, token: (saved?.token ?? 0) + 1 };
    for (const listener of listeners) listener();
  }
}
