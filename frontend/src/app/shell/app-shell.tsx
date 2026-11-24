import { useEffect, useRef, useState, type ReactNode, type UIEvent } from 'react';

import { useEditOptional } from '@/features/edit/edit-context';
import { useActivityReporting } from '@/features/export/activity';
import { useExportState } from '@/features/export/store';
import { StageScrollProvider } from '@/shared/lib/stage-scroll';
import { useLocale } from '@/shared/lib/i18n/locale';
import { cn } from '@/shared/lib/utils';
import { useViewportInsets } from '@/shared/lib/visual-viewport';

import { ConversationLog } from './conversation';
import { EditBridge } from './edit-bridge';
import { ShellViewProvider } from './shell-view';
import { Sidebar } from './sidebar';
import { TopBar } from './top-bar';
import { type Stage, type View } from './shell-config';

/** Below this a scroll is a stray pixel, not a reader moving down the screen. */
const SCROLLED_AT = 24;

/**
 * The widest work face: the scene list, the 9:16 preview at 462 / 796 of the
 * face height with a gutter on each side, and the editor at its widest.
 */
const STAGE_MAX_WIDTH =
  'calc(var(--layout-scene-col-w) + var(--layout-gutter) * 2 + 100cqh * 462 / 796 * 9 / 16 + var(--layout-scene-panel-max-w))';

function ExportHandoff({ videoId, view, draftWaiting, onStage }: {
  videoId: string | null;
  view: View;
  draftWaiting: boolean;
  onStage: (stage: Stage) => void;
}) {
  const edit = useEditOptional();
  const output = useExportState();
  const delivered = useRef<string | null>(null);
  const editForVideo = edit?.video?.id === videoId ? edit : null;
  const checking = view === 'export' && output.videoId === videoId && output.precheck.status === 'running';
  useActivityReporting(videoId, draftWaiting || checking || editForVideo?.jobWaiting === true);

  useEffect(() => {
    if (editForVideo === null) return;
    if (editForVideo.confirmedForOutput) {
      editForVideo.acknowledgeOutput();
      if (view === 'edit') onStage('export');
    }
    const finished = editForVideo.finishedGeneration;
    if (finished != null) {
      const attempt = `${finished}:${editForVideo.job?.attempt}`;
      if (attempt !== delivered.current) {
        delivered.current = attempt;
        if (view === 'edit' && editForVideo.job?.state !== 'cancelled') onStage('export');
      }
    }
  }, [editForVideo, onStage, view]);

  return null;
}

/**
 * The frame: a collapsed rail, the top bar, one body area and, on a phone, the
 * input docked at the bottom. The conversation column keeps the phone ratio of
 * its height, so the picture beside it never has to be squashed, and its log
 * opens with the sentence the video started from.
 */
export function AppShell({
  view,
  videoId = null,
  sentence = null,
  brand,
  onNewVideo,
  onStage,
  draftWaiting = false,
  header,
  jobStatus,
  announcer,
  composer,
  children,
}: {
  view: View;
  videoId?: string | null;
  /** The sentence the user sent on the first screen. */
  sentence?: string | null;
  brand: ReactNode;
  onNewVideo: () => void;
  onStage: (stage: Stage) => void;
  draftWaiting?: boolean;
  header?: ReactNode;
  jobStatus?: ReactNode;
  /** Stays mounted in every state so a screen reader hears each change once. */
  announcer?: ReactNode;
  composer: ReactNode | null;
  children: ReactNode;
}) {
  const { t } = useLocale();
  const { inset, keyboardOpen } = useViewportInsets();
  const [scrolled, setScrolled] = useState(false);
  const stage: Stage | null = view === 'first' ? null : view;

  useEffect(() => {
    setScrolled(false);
  }, [view]);

  const onScroll = (event: UIEvent<HTMLDivElement>) => {
    const next = event.currentTarget.scrollTop > SCROLLED_AT;
    setScrolled((previous) => (previous === next ? previous : next));
  };

  return (
    <ShellViewProvider value={view}>
      <EditBridge key={videoId} active={view === 'edit' || view === 'export'} videoId={videoId}>
        <ExportHandoff videoId={videoId} view={view} draftWaiting={draftWaiting} onStage={onStage} />
        <main
          data-screen="app"
          className="flex w-full overflow-hidden bg-[var(--surface)] md:bg-[var(--background)]"
          // A phone keyboard covers the bottom of the layout viewport without
          // resizing it, so the shell gives up exactly the covered height. The dock
          // then ends at the top of the keys instead of riding over the stage.
          style={{ height: keyboardOpen ? `calc(100dvh - ${inset}px)` : '100dvh' }}
        >
          {announcer}
          <Sidebar view={view} onNewVideo={onNewVideo} brand={brand} />
          <div className="flex min-h-0 min-w-0 flex-1 flex-col">
            <TopBar
              view={view}
              videoId={videoId}
              onStage={onStage}
              onNewVideo={onNewVideo}
              status={keyboardOpen ? jobStatus : null}
            />
            {/* While the keys are up the phone shows the sheet: step, panel and input. */}
            {keyboardOpen ? null : header}
            {/*
              From the first draft on, the conversation and the work area are two
              white faces on the app backdrop, a gap apart, so the eye never reads
              them as one sheet. The first screen has neither face.
            */}
            <div
              data-slot="workspace"
              style={stage === null ? undefined : { containerType: 'size' }}
              className={cn(
                'flex min-h-0 flex-1',
                stage !== null && 'md:gap-[var(--space-24)] md:bg-[var(--background)] md:p-[var(--space-24)]',
              )}
            >
              {stage !== null && composer !== null ? (
                <div
                  data-slot="conversation"
                  className="hidden shrink-0 flex-col rounded-[var(--radius-card)] bg-[var(--surface)] px-[var(--space-20)] pt-[18px] pb-[var(--space-20)] md:flex md:shadow-[var(--shadow-float)]"
                  // The width follows the face height (the row is the size container), so the
                  // 380 / 796 phone ratio of the layout tokens holds at every window size and engine.
                  style={{ width: 'calc(100cqh * 380 / 796)' }}
                >
                  <h2 className="mb-[14px] ml-[var(--space-4)] text-[22px] leading-[26px] font-bold text-[var(--text-strong)]">
                    {t('shell.conversation.title')}
                  </h2>
                  <div className="flex min-h-0 flex-1 flex-col gap-2">
                    <ConversationLog stage={stage} sentence={sentence} draftWaiting={draftWaiting} />
                    {composer}
                  </div>
                </div>
              ) : null}
              <section
                data-slot="stage"
                className={cn(
                  'flex min-h-0 min-w-0 flex-1 flex-col',
                  stage !== null &&
                    'md:mx-auto md:overflow-hidden md:rounded-[var(--radius-card)] md:bg-[var(--surface)] md:shadow-[var(--shadow-float)]',
                )}
                // The work face is as wide as the scene list, the 9:16 preview with its
                // side gutters and the widest editor; the rest of the row is split on
                // both sides so the face sits in the middle of the room beside the chat.
                style={stage === null ? undefined : { maxWidth: STAGE_MAX_WIDTH }}
              >
                <div
                  key={view === 'edit' ? 'edit' : 'stage'}
                  data-slot="stage-scroll"
                  className="flex min-h-0 flex-1 flex-col overflow-y-auto"
                  onScroll={onScroll}
                >
                  <StageScrollProvider scrolled={scrolled}>{children}</StageScrollProvider>
                </div>
                {stage !== null && composer !== null ? (
                  <div data-slot="composer-dock" className="shrink-0 px-3 pb-3 md:hidden">
                    {composer}
                  </div>
                ) : null}
              </section>
            </div>
          </div>
        </main>
      </EditBridge>
    </ShellViewProvider>
  );
}
