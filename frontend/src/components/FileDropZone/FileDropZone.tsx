import type { HTMLAttributes, ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { Upload } from 'lucide-react';

import { cn } from '@/shared/lib/utils';

import { usePresence } from '../use-presence';

import './FileDropZone.css';

export type FileDropZoneScope = 'screen' | 'container';

export type FileDropZoneProps = Omit<HTMLAttributes<HTMLDivElement>, 'children'> & {
  open: boolean;
  /** The line in the middle, for example "여기에 놓으면 올라가요". */
  label: string;
  /** The accepted kinds, for example "영상, BGM, 글 파일(.md, .txt)". */
  accept: string;
  icon?: ReactNode;
  /** The whole screen, or the positioned parent that receives the drop. */
  scope?: FileDropZoneScope;
  className?: string;
};



/**
 * The drop target. Screen scope covers the screen; container scope fills a
 * positioned parent so an editing surface receives only the files dropped on
 * its own target. The mask and the dashed frame are the two state rows; the
 * screen frame sits 24 inside the edge.
 */
export function FileDropZone({
  open,
  label,
  accept,
  icon,
  scope = 'screen',
  className,
  ...rest
}: FileDropZoneProps) {
  const { mounted, shown } = usePresence(open);
  if (!mounted) return null;

  const content = (
    <div
      {...rest}
      className={cn('file-drop', scope === 'container' && 'file-drop--container', className)}
      role="status"
      data-state={shown ? 'open' : 'closed'}
    >
      <div className="file-drop__mask" aria-hidden="true" />
      <div className="file-drop__frame">
        <span className="file-drop__icon" aria-hidden="true">
          {icon ?? <Upload />}
        </span>
        <p className="file-drop__title">{label}</p>
        <p className="file-drop__accept">{accept}</p>
      </div>
    </div>
  );

  if (scope === 'container' || typeof document === 'undefined') return content;
  return createPortal(content, document.body);
}
