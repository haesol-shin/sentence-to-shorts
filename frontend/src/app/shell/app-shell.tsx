import { useEffect, useRef, useState, type ReactNode, type UIEvent } from 'react';

import { EditChatHistory } from '@/features/edit/chat-history';
import { useEditOptional } from '@/features/edit/edit-context';
import { useActivityReporting } from '@/features/export/activity';
import { useExportState } from '@/features/export/store';
import { StageScrollProvider } from '@/shared/lib/stage-scroll';
import { useViewportInsets } from '@/shared/lib/visual-viewport';

import { EditBridge } from './edit-bridge';
import { ShellViewProvider } from './shell-view';
import { Sidebar } from './sidebar';
import { TopBar } from './top-bar';
import { type Stage, type View } from './shell-config';

/** Below this a scroll is a stray pixel, not a reader moving down the screen. */
const SCROLLED_AT = 24;

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
 * its height, so the picture beside it never has to be squashed.
 */
export function AppShell({
  view,
  videoId = null,
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
          className="flex w-full overflow-hidden bg-[var(--surface)]"
          // A phone keyboard covers the bottom of the layout viewport without
          // resizing it, so the shell gives up exactly the covered height. The dock
          // then ends at the top of the keys instead of riding over the stage.
          style={{ height: keyboardOpen ? `calc(100dvh - ${inset}px)` : '100dvh' }}
        >
          {announcer}
          <Sidebar view={view} onNewVideo={onNewVideo} />
          <div className="flex min-h-0 min-w-0 flex-1 flex-col">
            <TopBar
              brand={brand}
              view={view}
              videoId={videoId}
              onStage={onStage}
              status={keyboardOpen ? jobStatus : null}
            />
            {/* While the keys are up the phone shows the sheet: step, panel and input. */}
            {keyboardOpen ? null : header}
            <div className="flex min-h-0 flex-1">
              {stage !== null && composer !== null ? (
                <div
                  data-slot="conversation"
                  className={
                    view === 'edit' || view === 'export'
                      ? 'hidden min-w-[260px] shrink flex-col justify-end p-3 md:flex'
                      : 'hidden shrink-0 flex-col justify-end p-3 md:flex'
                  }
                  style={{
                    width:
                      view === 'edit' || view === 'export'
                        ? 'min(calc((100dvh - var(--layout-topbar-h) - 40px) * 0.477), 26vw)'
                        : undefined,
                    aspectRatio: 'var(--layout-conversation-aspect)',
                  }}
                >
                  {view === 'edit' || view === 'export' ? (
                    <div className="flex min-h-0 flex-1 flex-col gap-2">
                      <EditChatHistory />
                      {composer}
                    </div>
                  ) : (
                    composer
                  )}
                </div>
              ) : null}
              <section data-slot="stage" className="flex min-h-0 min-w-0 flex-1 flex-col">
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
