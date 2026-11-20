import { useRef, useState } from 'react';

import { PlaybackControls } from '@/components/PlaybackControls/PlaybackControls';
import { VideoPreview } from '@/components/VideoPreview/VideoPreview';
import { artifactUrl } from '@/shared/api/client';
import { mockMediaUrl } from '@/shared/api/mock/media';
import { useLocale } from '@/shared/lib/i18n/locale';

import { formatClock } from './model';

/**
 * The portrait player for the final MP4. Server media supports range requests
 * so seeking does not require downloading the whole file.
 */
export function ResultPlayer({
  artifactId,
  estimateSeconds,
  onDuration,
}: {
  artifactId: string;
  /** What the build expected the length to be, until the file says otherwise. */
  estimateSeconds: number | null;
  onDuration?: (seconds: number) => void;
}) {
  const { t } = useLocale();
  const video = useRef<HTMLVideoElement>(null);
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [length, setLength] = useState(0);
  const [muted, setMuted] = useState(false);
  const [failed, setFailed] = useState(false);
  const total = length > 0 ? length : (estimateSeconds ?? 0);
  const clock =
    total <= 0 ? '0:00' : length > 0 ? formatClock(total) : t('export.player.approx', { clock: formatClock(total) });

  return (
    <div data-slot="result-player" className="export-player">
      <VideoPreview
        label={t('export.player.label')}
        state="ready"
        duration={total > 0 ? formatClock(total) : undefined}
      >
        {failed ? (
          <p className="export-player__note" role="alert">
            {t('export.player.unavailable')}
          </p>
        ) : (
          <video
            ref={video}
            data-slot="result-video"
            className="export-player__video"
            src={import.meta.env.VITE_API_MODE === 'mock' ? mockMediaUrl('mp4') : artifactUrl(artifactId)}
            preload="metadata"
            playsInline
            muted={muted}
            onLoadedMetadata={(event) => {
              const seconds = event.currentTarget.duration;
              if (Number.isFinite(seconds) && seconds > 0) {
                setLength(seconds);
                onDuration?.(seconds);
              }
            }}
            onTimeUpdate={(event) => setTime(event.currentTarget.currentTime)}
            onPlay={() => setPlaying(true)}
            onPause={() => setPlaying(false)}
            onEnded={() => setPlaying(false)}
            onError={() => setFailed(true)}
          />
        )}
      </VideoPreview>
      <PlaybackControls
        label={t('export.player.controls')}
        playing={playing}
        onToggle={() => {
          const element = video.current;
          if (element === null) return;
          if (element.paused) void Promise.resolve(element.play()).catch(() => setFailed(true));
          else element.pause();
        }}
        position={length > 0 ? (time / length) * 100 : 0}
        onSeek={(position) => {
          const element = video.current;
          if (element !== null && length > 0) element.currentTime = (position / 100) * length;
        }}
        current={formatClock(time)}
        duration={clock}
        muted={muted}
        onToggleMute={() => setMuted((current) => !current)}
        disabled={failed}
      />
    </div>
  );
}
