import { API_BASE } from '@/shared/api/client';
import { mockMediaUrl } from '@/shared/api/mock/media';

/** Starts a file download without leaving the page. */
export function startDownload(href: string): void {
  const kind =
    import.meta.env.VITE_API_MODE === 'mock' && href.startsWith(`${API_BASE}/videos/`)
      ? /\/download\/(mp4|srt)$/u.exec(href)?.[1]
      : undefined;
  const mockAttachment = kind === 'mp4' || kind === 'srt';

  const link = document.createElement('a');
  link.href = mockAttachment ? mockMediaUrl(kind) : href;
  link.download = mockAttachment ? `example.${kind}` : '';
  link.rel = 'noopener';
  link.hidden = true;
  document.body.append(link);
  link.click();
  link.remove();
}
