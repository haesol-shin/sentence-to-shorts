import { useCallback, useEffect, useRef, useState } from 'react';

export type PreviewProblem = 'unavailable' | 'failed';

export interface AudioPreview {
  /** The key being loaded or played, or null while nothing sounds. */
  playing: string | null;
  /** The last press that did not sound, with the key it came from. */
  problem: { key: string; kind: PreviewProblem } | null;
  /** Starts the item, or stops it when it is the one sounding. Only one item sounds at a time. */
  toggle: (key: string, load: () => Promise<string | null>) => void;
  stop: () => void;
}

/** One shared player for the listen buttons of the sound tab: listening never selects anything. */
export function useAudioPreview(): AudioPreview {
  const element = useRef<HTMLAudioElement | null>(null);
  const token = useRef(0);
  const playingRef = useRef<string | null>(null);
  const [playing, setPlaying] = useState<string | null>(null);
  const [problem, setProblem] = useState<AudioPreview['problem']>(null);

  const setCurrent = useCallback((key: string | null) => {
    playingRef.current = key;
    setPlaying(key);
  }, []);

  const silence = useCallback(() => {
    token.current += 1;
    element.current?.pause();
    element.current = null;
  }, []);

  const stop = useCallback(() => {
    silence();
    setCurrent(null);
  }, [setCurrent, silence]);

  const toggle = useCallback(
    (key: string, load: () => Promise<string | null>) => {
      if (playingRef.current === key) {
        stop();
        return;
      }
      silence();
      const mine = token.current;
      setProblem(null);
      setCurrent(key);
      void (async () => {
        try {
          const url = await load();
          if (mine !== token.current) return;
          if (url === null) {
            setCurrent(null);
            setProblem({ key, kind: 'unavailable' });
            return;
          }
          const audio = new Audio(url);
          element.current = audio;
          audio.addEventListener('ended', () => {
            if (mine === token.current) {
              element.current = null;
              setCurrent(null);
            }
          });
          // A browser without media playback hands back nothing instead of a promise.
          const started: Promise<void> | undefined = audio.play();
          if (started !== undefined) await started;
        } catch {
          if (mine !== token.current) return;
          element.current = null;
          setCurrent(null);
          setProblem({ key, kind: 'failed' });
        }
      })();
    },
    [setCurrent, silence, stop],
  );

  useEffect(() => silence, [silence]);

  return { playing, problem, toggle, stop };
}
