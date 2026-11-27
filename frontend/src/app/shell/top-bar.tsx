import type { ReactNode } from 'react';

import { useConcept } from '@/features/concept/store';
import { useEditOptional } from '@/features/edit/edit-context';
import { EditNextAction } from '@/features/edit/next-action';
import { EditTopBarStatus } from '@/features/edit/top-bar-status';
import { ExportNextAction } from '@/features/export/next-action';
import { waitingPercent } from '@/features/runtime/prepare';
import { useScript } from '@/features/script/store';
import { useLocale } from '@/shared/lib/i18n/locale';
import { Button } from '@/components/Button/Button';
import { MenuButton } from '@/components/MenuButton/MenuButton';
import { Tag } from '@/components/Tag/Tag';
import { Tooltip } from '@/components/Tooltip/Tooltip';
import { TopBarItem } from '@/components/TopBarItem/TopBarItem';

import { useEditPrepare } from './edit-prepare';
import { HistoryButtons } from './history-buttons';
import { type Stage, type View } from './shell-config';
import { StageIndicator, StageMenu } from './stage-nav';
import { VideoSettings } from './video-settings';

/**
 * The edit stage's make-video button with what the voice models are doing. The
 * sentence for a download that cannot move has its own row under the bar
 * (`EditPrepareNotice`), so the bar keeps its layout and the tabs stay free.
 */
function EditAction() {
  const prepare = useEditPrepare();
  const edit = useEditOptional();
  const script = useScript();
  const rewriting = script?.document.id.split('#')[0] === edit?.video?.id &&
    (script?.busy || script?.rewrite != null || script?.settings != null || script?.tone != null);
  const held = edit?.phase !== 'video' && (edit?.chatBusy || edit?.pending != null || rewriting);
  return (
    <fieldset disabled={held} className="contents">
      <EditNextAction preparePercent={waitingPercent(prepare.view)} />
    </fieldset>
  );
}

/**
 * The video's name after undo and redo. The bar cuts a long name short, so the
 * menu heads with the whole name; it starts a new video as the rail does when
 * the frame hands it that action, and the video list waits with its reason
 * until that screen exists.
 */
function VideoTitle({ onNewVideo }: { onNewVideo?: () => void }) {
  const { t } = useLocale();
  const concept = useConcept();
  const title = concept?.document.topic.trim() ?? '';
  if (title === '') return null;
  return (
    <MenuButton
      label={t('shell.title.menu')}
      heading={title}
      trigger={<TopBarItem label={title} data-slot="video-title" className="max-w-80" />}
      items={[
        ...(onNewVideo === undefined ? [] : [{ value: 'new', label: t('shell.nav.newVideo') }]),
        {
          value: 'list',
          label: t('shell.nav.myVideos'),
          unavailable: true,
          unavailableName: `${t('shell.nav.myVideos')} · ${t('shell.nav.soon')}`,
          tag: <Tag>{t('shell.nav.soon')}</Tag>,
        },
      ]}
      note={t('shell.nav.myVideosReason')}
      onSelect={(value) => {
        if (value === 'new') onNewVideo?.();
      }}
    />
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
 * Undo, redo and the video's name on the left, the step tabs in the middle, the
 * next action on the right. The app name is not written here: the rail's logo
 * carries it. The phone swaps the tabs for the step menu, and its middle seat
 * also carries the short job status while a phone keyboard covers the header,
 * so the step menu and the action keep their own space. The first screen has
 * no top bar at all (SPEC 10a.2).
 */
export function TopBar({
  view,
  videoId = null,
  onStage,
  onNewVideo,
  status,
}: {
  view: View;
  videoId?: string | null;
  onStage: (stage: Stage) => void;
  onNewVideo?: () => void;
  status?: ReactNode;
}) {
  if (view === 'first') return null;
  const stage: Stage = view;

  return (
    <header
      data-slot="top-bar"
      // The desktop bar is a white strip 56 high whose controls hang 6 from its top edge.
      className="relative flex min-h-[var(--layout-topbar-h)] shrink-0 items-center gap-3 bg-[var(--surface)] px-4 md:h-14 md:min-h-0 md:items-start md:gap-4 md:pt-1.5"
    >
      {/* The name sits 12 after redo, as the canon draws the bar. */}
      <div className="hidden min-w-0 gap-3 md:flex">
        <HistoryButtons view={view} />
        <VideoTitle onNewVideo={onNewVideo} />
      </div>
      <div className="shrink-0 md:hidden">
        <StageMenu current={stage} onSelect={onStage} />
      </div>
      <div className="absolute left-1/2 hidden -translate-x-1/2 md:block">
        <StageIndicator current={stage} onSelect={onStage} />
      </div>
      {/* Export opens from the edit step, so its bar keeps the edit step's video settings. */}
      {view === 'edit' || view === 'export' ? (
        <div className="flex min-w-0 flex-1 items-center justify-end gap-2 md:min-h-[var(--size-control)]">
          {view === 'edit' ? <EditTopBarStatus /> : status}
          <VideoSettings />
        </div>
      ) : (
        <div className="flex min-w-0 flex-1 items-center md:min-h-[var(--size-control)]">{status}</div>
      )}
      {stage === 'script' ? null : <NextAction stage={stage} videoId={videoId} />}
    </header>
  );
}
