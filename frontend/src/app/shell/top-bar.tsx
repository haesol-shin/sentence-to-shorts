import type { ReactNode } from 'react';

import { useEditOptional } from '@/features/edit/edit-context';
import { EditNextAction } from '@/features/edit/next-action';
import { EditTopBarStatus } from '@/features/edit/top-bar-status';
import { ExportNextAction } from '@/features/export/next-action';
import { waitingPercent } from '@/features/runtime/prepare';
import { PrepareNotice } from '@/features/runtime/prepare-notice';
import { usePrepare } from '@/features/runtime/use-prepare';
import { cn } from '@/shared/lib/utils';
import { useLocale } from '@/shared/lib/i18n/locale';
import { Button } from '@/components/Button/Button';
import { Tooltip } from '@/components/Tooltip/Tooltip';

import { HistoryButtons } from './history-buttons';
import { showsStageIndicator, type Stage, type View } from './shell-config';
import { StageIndicator, StageMenu } from './stage-nav';
import { VideoSettings } from './video-settings';

/**
 * The edit stage's make-video button with what the voice models are doing. The
 * sentence for a download that cannot move floats under the top bar, so the
 * bar keeps its layout.
 */
function EditAction() {
  const edit = useEditOptional();
  const prepare = usePrepare(edit?.video?.settings.language ?? null);
  return (
    <>
      <EditNextAction preparePercent={waitingPercent(prepare.view)} />
      <PrepareNotice
        status={prepare}
        className="absolute top-full right-4 z-[var(--z-panel)] mt-2 w-[360px] max-w-[calc(100vw-32px)] rounded-[var(--radius-surface)] bg-[var(--popover)] p-2 shadow-[var(--shadow-float)]"
      />
    </>
  );
}

/**
 * The right-hand action the shell keeps a seat for (SPEC 10a.2). Each stage
 * names its own action, and until that stage can carry it the seat stays shut
 * with the reason in a tooltip. The phone gets a shorter word so the seat, the
 * step menu and the screen stay inside 390px.
 */
function NextAction({ stage, videoId }: { stage: Stage; videoId: string | null }) {
  const { t } = useLocale();
  if (stage === 'edit') return <EditAction />;
  if (stage === 'export') return <ExportNextAction videoId={videoId} />;
  const label = t(`shell.nextAction.${stage}`);
  return (
    <Tooltip content={t('shell.nextAction.reason')} side="top">
      <span tabIndex={0} className="inline-flex shrink-0" data-slot="next-action-seat">
        <Button data-slot="next-action" aria-label={label} className="shrink-0" disabled>
          <span className="hidden md:inline">{label}</span>
          <span className="md:hidden">{t(`shell.nextActionShort.${stage}`)}</span>
        </Button>
      </span>
    </Tooltip>
  );
}

/**
 * Undo and redo on the left, step navigation on the way, the next action on the
 * right. The app name is not written here: the rail's logo carries it. The
 * middle seat also carries the short job status while a phone keyboard covers
 * the header, so the step menu and the action keep their own space. The first
 * screen has no top bar at all (SPEC 10a.2).
 */
export function TopBar({
  view,
  videoId = null,
  onStage,
  status,
}: {
  view: View;
  videoId?: string | null;
  onStage: (stage: Stage) => void;
  status?: ReactNode;
}) {
  if (view === 'first') return null;
  const stage: Stage = view;

  return (
    <header
      data-slot="top-bar"
      className="relative flex shrink-0 items-center gap-3 px-4"
      style={{ minHeight: 'var(--layout-topbar-h)' }}
    >
      <div className="hidden md:block">
        <HistoryButtons view={view} />
      </div>
      <div className={cn('shrink-0', showsStageIndicator(stage) && 'md:hidden')}>
        <StageMenu current={stage} onSelect={onStage} />
      </div>
      {showsStageIndicator(stage) ? (
        <div className="absolute left-1/2 hidden -translate-x-1/2 md:block">
          <StageIndicator current={stage} onSelect={onStage} />
        </div>
      ) : null}
      {view === 'edit' ? (
        <div className="flex min-w-0 flex-1 items-center justify-end gap-2">
          <EditTopBarStatus />
          <VideoSettings />
        </div>
      ) : (
        <div className="flex min-w-0 flex-1 items-center">{status}</div>
      )}
      {stage === 'script' ? null : <NextAction stage={stage} videoId={videoId} />}
    </header>
  );
}
