import type { BgmChoice, Mood } from '../api';
import type { SettingChange } from '../edit-context';
import type { Video } from '../model';

/**
 * The whole BGM object is one change unit. A change path allows only letters and
 * underscores, so the level field `gain_db_x10` cannot be addressed on its own.
 */
export const BGM_PATH = '/settings/audio/bgm';
export const VOICE_PATH = '/settings/audio/voice';

export type BgmSetting = Video['settings']['audio']['bgm'];

/** The six moods the contract names, in the order the picker lists them. */
export const MOODS: readonly Mood[] = [
  'curious',
  'playful',
  'tense',
  'energetic',
  'calm',
  'reflective',
];

/**
 * The reviewed BGM levels, in tenths of a dB. Free numbers can drown the voice,
 * so the tab offers these three and nothing between them.
 */
export const BGM_GAINS: readonly number[] = [-200, -120, -60];

/** The BGM a new video starts with. A recorded video that lacks a value reads as this. */
const DEFAULT_MOOD: Mood = 'curious';
const DEFAULT_GAIN = -120;

export interface AudioView {
  voiceId: string | null;
  bgm: {
    enabled: boolean;
    mood: Mood;
    entryId: string | null;
    gain: number;
    ducking: boolean;
  };
}

function idOf(ref: unknown): string | null {
  if (typeof ref !== 'object' || ref === null || !('id' in ref)) return null;
  return typeof ref.id === 'string' && ref.id !== '' ? ref.id : null;
}

/** The sound values of a video. A value the video does not carry reads as its default. */
export function readAudio(video: Video | null): AudioView {
  const audio = video?.settings.audio;
  const bgm = audio?.bgm;
  const mood = bgm?.mood;
  return {
    voiceId: idOf(audio?.voice),
    bgm: {
      enabled: bgm?.enabled ?? true,
      mood: mood !== undefined && MOODS.includes(mood) ? mood : DEFAULT_MOOD,
      entryId: idOf(bgm?.entry),
      gain: typeof bgm?.gain_db_x10 === 'number' ? bgm.gain_db_x10 : DEFAULT_GAIN,
      ducking: bgm?.ducking ?? true,
    },
  };
}

/** The tracks of one mood, built-in ones first and the user's own after them. */
export function tracksOfMood(tracks: readonly BgmChoice[], mood: Mood): BgmChoice[] {
  const order = { builtin: 0, upload: 1, code: 2 } as const;
  return tracks
    .filter((track) => track.mood === mood)
    .sort((a, b) => order[a.source] - order[b.source]);
}

/** The BGM object with some fields changed, as the one change that writes it. */
export function bgmChange(video: Video | null, patch: Partial<BgmSetting>): SettingChange[] {
  if (video === null) return [];
  const { bgm } = readAudio(video);
  const next: BgmSetting = {
    enabled: bgm.enabled,
    mood: bgm.mood,
    entry: video.settings.audio.bgm?.entry ?? null,
    gain_db_x10: bgm.gain,
    ducking: bgm.ducking,
    ...patch,
  };
  return [{ path: BGM_PATH, value: next }];
}

/** A track and its mood travel together, so the video never holds a track of another mood. */
export function trackPatch(track: BgmChoice): Partial<BgmSetting> {
  return { entry: { id: track.id, revision: track.revision }, mood: track.mood };
}

/** A new mood requires a matching track; otherwise leave both saved values alone. */
export function moodPatch(
  tracks: readonly BgmChoice[],
  mood: Mood,
  current: AudioView['bgm'],
): Partial<BgmSetting> | null {
  if (mood === current.mood) return null;
  const own = tracksOfMood(tracks, mood);
  const kept = own.find((track) => track.id === current.entryId) ?? own[0];
  return kept === undefined ? null : trackPatch(kept);
}
