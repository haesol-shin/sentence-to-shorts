import type { ReactNode } from 'react';

/** The gallery's top bar. Case frames load without it, so a screenshot stays one case. */
export function GalleryTop({
  tab,
  batch = 1,
}: {
  tab: 'cases' | 'copy';
  batch?: number;
}): ReactNode {
  return (
    <header className="gallery-top">
      <strong className="gallery-top__brand">갤러리</strong>
      <nav className="gallery-top__tabs" aria-label="갤러리 보기">
        <a href={`?batch=${batch}`} aria-current={tab === 'cases' ? 'page' : undefined}>
          화면 사례
        </a>
        <a href="?tab=copy" aria-current={tab === 'copy' ? 'page' : undefined}>
          문구
        </a>
      </nav>
    </header>
  );
}
