import type { ReactNode } from 'react';

import { cn } from '@/shared/lib/utils';
import { useLocale } from '@/shared/lib/i18n/locale';
import { Button } from '@/shared/ui/button';
import { Tooltip } from '@/shared/ui/tooltip';

import { showsStageIndicator, type Stage, type View } from './shell-config';
import { StageIndicator, StageMenu } from './stage-nav';

/**
 * The right-hand action the shell keeps a seat for (SPEC 10a.2). Each stage
 * names its own action, and until that stage can carry it the seat stays shut
 * with the reason in a tooltip. The phone gets a shorter word so the seat, the
 * step menu and the screen stay inside 390px.
 */
function NextAction({ stage }: { stage: Stage }) {
  const { t } = useLocale();
  const label = t(`shell.nextAction.${stage}`);
  return (
    <Tooltip label={t('shell.nextAction.reason')} side="top">
      <Button
        data-slot="next-action"
        aria-label={label}
        className="w-max shrink-0 px-3 whitespace-nowrap"
        disabled
      >
        <span className="hidden md:inline">{label}</span>
        <span className="md:hidden">{t(`shell.nextActionShort.${stage}`)}</span>
      </Button>
    </Tooltip>
  );
}

/**
 * Brand on the left, step navigation on the way, the next action on the right.
 * The middle seat also carries the short job status while a phone keyboard
 * covers the header, so the step menu and the action keep their own space.
 * The first screen carries no step navigation at all, and on a phone it needs
 * no top bar at all (SPEC 10a.2).
 */
export function TopBar({
  brand,
  view,
  onStage,
  status,
}: {
  brand: ReactNode;
  view: View;
  onStage: (stage: Stage) => void;
  status?: ReactNode;
}) {
  const stage: Stage | null = view === 'first' ? null : view;

  return (
    <header
      data-slot="top-bar"
      className={cn(
        'relative shrink-0 items-center gap-3 px-4',
        view === 'first' ? 'hidden md:flex' : 'flex',
      )}
      style={{ minHeight: 'var(--layout-topbar-h)' }}
    >
      <span
        data-slot="brand"
        className="hidden max-w-40 truncate text-[15px] font-bold text-[var(--text-strong)] md:inline"
      >
        {brand}
      </span>
      {stage === null ? null : (
        <>
          <div className={cn('shrink-0', showsStageIndicator(stage) && 'md:hidden')}>
            <StageMenu current={stage} onSelect={onStage} />
          </div>
          {showsStageIndicator(stage) ? (
            <div className="absolute left-1/2 hidden -translate-x-1/2 md:block">
              <StageIndicator current={stage} onSelect={onStage} />
            </div>
          ) : null}
        </>
      )}
      <div className="flex min-w-0 flex-1 items-center">{status}</div>
      {stage === null || stage === 'script' ? null : <NextAction stage={stage} />}
    </header>
  );
}
