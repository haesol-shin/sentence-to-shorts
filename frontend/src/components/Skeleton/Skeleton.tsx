import type { CSSProperties } from 'react';

import { cn } from '@/shared/lib/utils';

import './Skeleton.css';

export type SkeletonShape = 'text' | 'script' | 'thumb' | 'media';

export type SkeletonProps = {
  shape?: SkeletonShape;
  /** Overrides the shape width in px. */
  width?: number;
  /** Overrides the shape height in px. */
  height?: number;
  className?: string;
};



/** A grey block where a picture, a line or a whole stage will arrive. */
export function Skeleton({ shape = 'text', width, height, className }: SkeletonProps) {
  const style = {
    ...(width === undefined ? {} : { width: `${width}px` }),
    ...(height === undefined ? {} : { height: `${height}px` }),
  } as CSSProperties;

  return (
    <div
      className={cn('skeleton', className)}
      data-shape={shape}
      style={style}
      aria-hidden="true"
    />
  );
}
