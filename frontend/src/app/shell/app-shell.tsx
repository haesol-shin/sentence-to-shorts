import { useEffect, useState, type ReactNode, type UIEvent } from 'react';

import { EditChatHistory } from '@/features/edit/chat-history';
import { StageScrollProvider } from '@/shared/lib/stage-scroll';
import { useViewportInsets } from '@/shared/lib/visual-viewport';

import { EditBridge } from './edit-bridge';
import { ShellViewProvider } from './shell-view';
import { Sidebar } from './sidebar';
import { TopBar } from './top-bar';
import { type Stage, type View } from './shell-config';

/** Below this a scroll is a stray pixel, not a reader moving down the screen. */
const SCROLLED_AT = 24;

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
      <EditBridge active={view === 'edit'} videoId={videoId}>
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
                    view === 'edit'
                      ? 'hidden min-w-[260px] shrink flex-col justify-end p-3 md:flex'
                      : 'hidden shrink-0 flex-col justify-end p-3 md:flex'
                  }
                  style={{
                    width:
                      view === 'edit'
                        ? 'min(calc((100dvh - var(--layout-topbar-h) - 40px) * 0.477), 26vw)'
                        : undefined,
                    aspectRatio: 'var(--layout-conversation-aspect)',
                  }}
                >
                  {view === 'edit' ? (
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
