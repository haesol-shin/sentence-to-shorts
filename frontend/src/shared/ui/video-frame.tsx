import type { ReactNode } from 'react';

import { cn } from '@/shared/lib/utils';

/**
 * A 9:16 video frame. The height decides the width, so the picture is never
 * squashed; editing rounds the corner with one token, playback and export do
 * not (DESIGN: video corner).
 */
export function VideoFrame({
  className,
  children,
}: {
  className?: string;
  children?: ReactNode;
}) {
  return (
    <div
      data-slot="video-frame"
      className={cn('relative overflow-hidden bg-[var(--surface-sunken)]', className)}
      style={{
        aspectRatio: 'var(--layout-preview-aspect)',
        borderRadius: 'var(--radius-video)',
      }}
    >
      {children}
    </div>
  );
}
