import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Film, Maximize } from 'lucide-react';

import { Button } from '@/components/Button/Button';
import { CloseButton } from '@/components/CloseButton/CloseButton';
import { Dialog, DialogClose } from '@/components/Dialog/Dialog';
import { PlaybackControls } from '@/components/PlaybackControls/PlaybackControls';
import { IconButton } from '@/components/IconButton/IconButton';
import { VideoFrame } from '@/shared/ui/video-frame';
import { useLocale } from '@/shared/lib/i18n/locale';
import { cn } from '@/shared/lib/utils';

import { artifactUrl } from './api';
import type { EditValue } from './edit-context';
import { estimatedSeconds, sceneNumber, stillIsReady, stillState, type Line, type Span } from './model';

function formatClock(seconds: number): string {
  return `0:${String(seconds).padStart(2, '0')}`;
}

function HighlightedLine({ text, spans }: { text: string; spans: readonly Span[] }) {
  const points = Array.from(text);
  const sorted = [...spans].sort((left, right) => left.start - right.start);
  const nodes: Array<string | { text: string; start: number }> = [];
  let cursor = 0;
  for (const span of sorted) {
    if (span.start > cursor) nodes.push(points.slice(cursor, span.start).join(''));
    nodes.push({ text: points.slice(span.start, span.end).join(''), start: span.start });
    cursor = span.end;
  }
  if (cursor < points.length) nodes.push(points.slice(cursor).join(''));

  return (
    <>
      {nodes.map((node, index) =>
        typeof node === 'string' ? (
          <span key={`${index}-${node}`}>{node}</span>
        ) : (
          <span
            key={`${node.start}-${node.text}`}
            className="text-[var(--emphasis)] underline decoration-2 underline-offset-2"
          >
            {node.text}
          </span>
        ),
      )}
    </>
  );
}

function StillFrame({
  edit,
  className,
  caption,
}: {
  edit: EditValue;
  className?: string;
  caption?: ReactNode;
}) {
  const { t } = useLocale();
  const scene = edit.selectedScene;
  const state = scene === null ? 'missing' : stillState(edit.build, scene.id);
  const ready = scene !== null && stillIsReady(edit.build, scene.id);
  const number = sceneNumber(edit.video, edit.selectedId);

  return (
    <VideoFrame className={className}>
      {scene === null ? (
        <div className="flex h-full w-full flex-col items-center justify-center gap-2 p-4 text-center text-[var(--text-muted)]">
          <Film aria-hidden size={32} />
          <p className="text-[15px]">{t('edit.preview.noScene')}</p>
        </div>
      ) : ready ? (
        <div
          data-state="fresh"
          role="img"
          aria-label={t('edit.preview.still', { number, label: scene.beat_label })}
          className="relative h-full w-full bg-[var(--surface-sunken)]"
        >
          {edit.build?.scenes[scene.id]?.still.artifact === null ||
          edit.build?.scenes[scene.id]?.still.artifact === undefined ? null : (
            <img
              data-slot="preview-still"
              src={artifactUrl(edit.build.scenes[scene.id]!.still.artifact!.id)}
              alt=""
              className="h-full w-full object-cover"
            />
          )}
          <span className="absolute right-3 bottom-3 rounded-[var(--radius-pill)] bg-[var(--overlay-length)] px-2 text-[12px] text-[var(--primary-foreground)]">
            {t('edit.scene.estimated', { seconds: estimatedSeconds(scene) })}
          </span>
        </div>
      ) : state === 'building' ? (
        <div
          data-state="building"
          className="flex h-full w-full flex-col items-center justify-center gap-2 p-4 text-center text-[var(--text-muted)]"
        >
          <span className="spinner text-[var(--emphasis)]" aria-hidden="true" />
          <p className="text-[15px]">{t('edit.preview.building')}</p>
        </div>
      ) : (
        <div
          data-state={state}
          className="flex h-full w-full flex-col items-center justify-center gap-2 p-4 text-center text-[var(--text-muted)]"
        >
          <Film aria-hidden size={32} />
          <p className="text-[15px]">
            {state === 'stale'
              ? t('edit.preview.stale')
              : state === 'failed'
                ? t('edit.preview.failed')
                : t('edit.preview.missing')}
          </p>
        </div>
      )}
      {ready ? caption : null}
    </VideoFrame>
  );
}

export function ScenePreview({ edit, collapsed }: { edit: EditValue; collapsed: boolean }) {
  const { t } = useLocale();
  const [playing, setPlaying] = useState(false);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [muted, setMuted] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const elapsedRef = useRef(0);
  const scene = edit.selectedScene;
  const lines: Line[] = scene?.lines ?? [];
  const seconds = estimatedSeconds(scene);
  const totalMs = Math.max(1000, seconds * 1000);
  const weights = lines.map((line) => Math.max(1, Array.from(line.display_text).length));
  const weightTotal = weights.reduce((total, weight) => total + weight, 0) || 1;
  let cumulative = 0;
  let lineIndex = 0;
  for (let index = 0; index < lines.length; index += 1) {
    cumulative += (weights[index] ?? 1) / weightTotal;
    if (elapsedMs / totalMs < cumulative) {
      lineIndex = index;
      break;
    }
    lineIndex = index;
  }
  const line = lines[lineIndex];
  const position = Math.min(100, (elapsedMs / totalMs) * 100);
  const caption =
    line === undefined ? undefined : (
      <p
        data-slot="preview-caption"
        className="pointer-events-none absolute right-3 bottom-3 left-3 rounded-[var(--radius-content)] bg-[var(--overlay-caption)] px-2 py-1 text-center text-[15px] leading-[22px] text-[var(--text-strong)]"
      >
        <HighlightedLine text={line.display_text} spans={line.highlight} />
      </p>
    );

  useEffect(() => {
    setPlaying(false);
    setElapsedMs(0);
    elapsedRef.current = 0;
  }, [scene?.id]);

  useEffect(() => {
    if (!playing) return undefined;
    const started = Date.now() - elapsedRef.current;
    const timer = window.setInterval(() => {
      const next = Date.now() - started;
      elapsedRef.current = next;
      if (next >= totalMs) {
        setElapsedMs(totalMs);
        setPlaying(false);
      } else {
        setElapsedMs(next);
      }
    }, 50);
    return () => window.clearInterval(timer);
  }, [playing, totalMs]);

  const seek = (percent: number) => {
    const next = Math.max(0, Math.min(100, percent));
    const value = (next / 100) * totalMs;
    elapsedRef.current = value;
    setElapsedMs(value);
  };

  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-2">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-[22px] leading-8 font-bold text-[var(--text-strong)]">
          {t('edit.preview.title')}
        </h2>
        <div className="flex items-center gap-1">
          <IconButton label={t('edit.preview.expand')} onClick={() => setExpanded(true)}>
            <Maximize aria-hidden size={20} />
          </IconButton>
        </div>
      </div>

      <div className="flex min-h-0 flex-1 items-center justify-center">
        <div className="edit-preview-area relative flex h-full max-h-full min-h-0 w-full items-center justify-center">
          <StillFrame
            edit={edit}
            className={cn(
              collapsed ? 'h-[var(--layout-thumb-h)] w-auto' : 'h-[var(--layout-mobile-preview-h)] w-auto',
            )}
            caption={caption}
          />
        </div>
      </div>

      <div className="edit-preview-controls min-w-0">
        <PlaybackControls
          label={t('edit.preview.play')}
          playing={playing}
          onToggle={() => {
            if (lines.length === 0) return;
            if (!playing && elapsedMs >= totalMs) seek(0);
            setPlaying((current) => !current);
          }}
          position={position}
          onSeek={(next) => {
            if (lines.length === 0) return;
            setPlaying(false);
            seek(next);
          }}
          current={formatClock(Math.floor(elapsedMs / 1000))}
          duration={`약 ${formatClock(seconds)}`}
          muted={muted}
          onToggleMute={() => setMuted((current) => !current)}
          disabled={lines.length === 0}
        />
      </div>
      <p className="text-center text-[15px] text-[var(--text-muted)]">{t('edit.preview.note')}</p>

      <Dialog
        open={expanded}
        onOpenChange={setExpanded}
        title={t('edit.preview.title')}
        description={scene === null ? t('edit.preview.noScene') : scene.beat_label}
        label={t('edit.preview.title')}
        actions={
          <DialogClose render={<Button variant="ghost">{t('edit.preview.close')}</Button>} />
        }
      >
        <DialogClose
          render={
            <CloseButton
              label={t('edit.preview.close')}
              data-slot="preview-close"
              className="absolute top-4 right-4"
            />
          }
        />
        <div className="flex max-h-[70vh] justify-center py-2">
          <StillFrame edit={edit} className="h-[70vh] w-auto" caption={caption} />
        </div>
      </Dialog>
    </div>
  );
}
