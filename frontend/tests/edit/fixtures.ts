import type {
  ArtifactStatus,
  Scene,
  Video,
  VideoBuild,
  VideoView,
} from '@/features/edit/model';

function status(state: ArtifactStatus['state']): ArtifactStatus {
  return state === 'fresh'
    ? {
        state,
        cache_key: '0'.repeat(64),
        artifact: { id: 'a_0'.padEnd(27, '0'), digest: '0'.repeat(64), cache_key: '0'.repeat(64) },
        error_code: null,
      }
    : { state, cache_key: null, artifact: null, error_code: null };
}

function line(id: string, text: string, highlight: { start: number; end: number }[] = []) {
  return {
    id,
    display_text: text,
    speech_text: text,
    speaker: 'narrator' as const,
    highlight,
  };
}

function scene(
  id: string,
  beatId: string,
  label: string,
  lines: Scene['lines'],
  anchor: 'left' | 'center' | 'top_right',
): Scene {
  return {
    id,
    beat_id: beatId,
    beat_label: label,
    lines,
    visual: {
      background_id: 'bg_village',
      characters: [
        { anchor, expression_id: 'expr_happy', pose_id: 'pose_idle', motion: 'none' },
      ],
      elements: [],
      sfx: [],
      transition_in: 'cut',
    },
  };
}

export function makeVideo(): Video {
  return {
    schema_version: 2,
    id: 'v_0test00000000000000000000',
    project_id: 'p_0test00000000000000000000',
    owner_id: 'owner',
    revision: 1,
    parent_revision: null,
    created_at: '2026-11-20T00:00:00Z',
    created_by: 'create',
    change_id: null,
    stage: 'scenes_confirmed',
    derived_from: null,
    topic: '커피를 고르는 세 가지 기준',
    material: [],
    reference: null,
    settings: {
      language: 'ko',
      target_duration_s: 30,
      format: {},
      visual: {},
      audio: {
        voice: { id: 'fixed_wav', revision: '0'.repeat(64) },
        bgm: { enabled: true, mood: 'curious', entry: {}, gain_db_x10: 0, ducking: true },
        sfx_enabled: true,
      },
      caption: {},
      motion: {},
      locks: {},
      origins: {},
      extra_instructions: [],
    },
    script: { source: 'llm', raw_text: null, title: null },
    scene_order: ['s_0scene1000000000000000000', 's_0scene2000000000000000000', 's_0scene3000000000000000000'],
    scenes: {
      s_0scene1000000000000000000: scene(
        's_0scene1000000000000000000',
        'hook',
        '훅',
        [
          line('l_0line10000000000000000000', '첫 줄'),
          line('l_0line20000000000000000000', '둘째 줄'),
        ],
        'center',
      ),
      s_0scene2000000000000000000: scene(
        's_0scene2000000000000000000',
        'first',
        '첫 번째',
        [line('l_0line30000000000000000000', '커피를 고르는 기준은 세 가지뿐이다.')],
        'left',
      ),
      s_0scene3000000000000000000: scene(
        's_0scene3000000000000000000',
        'second',
        '두 번째',
        [line('l_0line40000000000000000000', '물의 온도를 지킨다.')],
        'top_right',
      ),
    },
  } as unknown as Video;
}

export function makeBuild(): VideoBuild {
  return {
    video_id: 'v_0test00000000000000000000',
    revision: 1,
    scenes: {
      s_0scene1000000000000000000: {
        still: status('fresh'),
        tts: {},
        timing: status('missing'),
        layer: null,
        clip: status('missing'),
      },
      s_0scene2000000000000000000: {
        still: status('stale'),
        tts: {},
        timing: status('missing'),
        layer: null,
        clip: status('missing'),
      },
      s_0scene3000000000000000000: {
        still: status('missing'),
        tts: {},
        timing: status('missing'),
        layer: null,
        clip: status('missing'),
      },
    },
    mix: status('missing'),
    final: status('missing'),
    srt: status('missing'),
    estimated_ms: 0,
    actual_ms: null,
    attribution: [],
  } as unknown as VideoBuild;
}

export function makeView(): VideoView {
  return {
    video: makeVideo(),
    build: makeBuild(),
    open_jobs: [],
    pending_change: null,
  } as unknown as VideoView;
}
