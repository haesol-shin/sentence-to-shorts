import { Notice } from '@/components/Notice/Notice';
import { useLocale } from '@/shared/lib/i18n/locale';

import type { CaptionIssue } from './model';

/** A check that failed or that the layout flags; `kept` adds that the app leaves the picked value alone. */
export interface ShownIssue extends CaptionIssue {
  tone: 'error' | 'warning';
  kept?: boolean;
}

/** The failed caption checks, each with the layer it belongs to and, for missing text, the lines. */
export function CaptionIssues({ issues }: { issues: readonly ShownIssue[] }) {
  const { t } = useLocale();
  if (issues.length === 0) return null;
  return (
    <div data-slot="caption-issues" className="flex flex-col gap-2">
      {issues.map((issue) => {
        const places = issue.lines.map((place) =>
          t('audio.caption.line', { scene: place.sceneNumber, line: place.lineNumber }),
        );
        const text = t(`audio.caption.issue.${issue.code}`, {
          layer: t(`audio.caption.layer.${issue.layer}`),
          lines: places.length === 0 ? '' : ` ${places.join(', ')}`,
        });
        return (
          <Notice key={issue.code} tone={issue.tone}>
            {issue.kept === true ? `${text} ${t('audio.caption.issue.kept')}` : text}
          </Notice>
        );
      })}
    </div>
  );
}
