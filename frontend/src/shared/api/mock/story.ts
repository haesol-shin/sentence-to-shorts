import type { Video, VideoView } from '../client';

type Anchor = NonNullable<Video['scenes'][string]['visual']>['characters'][number]['anchor'];

interface MockStoryScene {
  lines: readonly string[];
  /** The scene picture's placeholder colour, by the scene's place in the design pictures. */
  art: string;
  anchor: Anchor;
  /** The word the caption stresses. */
  highlight: string;
}

/**
 * The synthetic story every mock screen shows: five scenes of a video about a
 * day without the internet, with the scene and line counts, picture colours,
 * character places and stressed words the design pictures draw. The script
 * draft and the edit, result and making screens read the same scenes, so a
 * screen compared with its picture differs in layout only.
 */
const MOCK_STORY: readonly MockStoryScene[] = [
  { lines: ['인터넷이 하루 멈추면', '카드 결제가 안 돼요'], art: '#D8D8C6', anchor: 'middle_center', highlight: '인터넷' },
  { lines: ['지도 앱도 멈추고', '길 찾기가 어려워요'], art: '#CFE3D2', anchor: 'middle_left', highlight: '지도' },
  { lines: ['편의점에선 현금만 받아요', '현금이 없으면 못 사요', '줄이 길어져요'], art: '#E6D3C3', anchor: 'middle_center', highlight: '현금' },
  { lines: ['메신저가 안 되니', '사람들이 직접 만나요'], art: '#E3CFE0', anchor: 'middle_right', highlight: '만나요' },
  { lines: ['하루가 지나면', '다시 연결돼요'], art: '#C8E0E3', anchor: 'middle_center', highlight: '연결' },
];

export const MOCK_STORY_LINES: readonly (readonly string[])[] = MOCK_STORY.map((scene) => scene.lines);

/** A flat 9:16 picture in the scene's colour; the app shows `data:image/` artifact ids as they are. */
function stillOf(art: string): string {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="9" height="16"><rect width="9" height="16" fill="${art}"/></svg>`;
  return `data:image/svg+xml,${encodeURIComponent(svg)}`;
}

/**
 * The recorded video with the story's scenes. Each scene keeps its first line's
 * id, which its sound cues point at; the lines the story adds get fresh ids.
 * The stressed word is marked on the first line that holds it.
 */
export function withMockStory(video: Video): Video {
  const scenes = { ...video.scenes };
  video.scene_order.forEach((sceneId, sceneIndex) => {
    const scene = scenes[sceneId];
    const story = MOCK_STORY[sceneIndex];
    if (scene === undefined || story === undefined) return;
    const [first] = scene.lines;
    const stressed = story.lines.findIndex((text) => text.includes(story.highlight));
    scenes[sceneId] = {
      ...scene,
      lines: story.lines.map((text, lineIndex) => {
        const start = lineIndex === stressed ? Array.from(text.slice(0, text.indexOf(story.highlight))).length : -1;
        return {
          speaker: first?.speaker ?? 'narrator',
          highlight: start < 0 ? [] : [{ start, end: start + Array.from(story.highlight).length }],
          id: lineIndex === 0 && first !== undefined
            ? first.id
            : `l_0story${sceneIndex}${lineIndex}`.padEnd(28, '0'),
          display_text: text,
          speech_text: text,
        };
      }),
      visual: scene.visual === undefined || scene.visual === null ? scene.visual : {
        ...scene.visual,
        characters: scene.visual.characters.map((character, index) =>
          index === 0 ? { ...character, anchor: story.anchor } : character),
      },
    };
  });
  return { ...video, scenes };
}

/**
 * The recorded build with every story scene's picture made, as the design
 * pictures open the edit step after the pictures are drawn.
 */
export function withMockStoryStills(build: VideoView['build'], video: Video): VideoView['build'] {
  const scenes = { ...build.scenes };
  video.scene_order.forEach((sceneId, sceneIndex) => {
    const story = MOCK_STORY[sceneIndex];
    if (story === undefined) return;
    const id = stillOf(story.art);
    const digest = '0'.repeat(64);
    const missing = { state: 'missing' as const, cache_key: null, artifact: null, error_code: null };
    // The recording builds only some scenes; the others start with nothing made.
    const current = scenes[sceneId] as VideoView['build']['scenes'][string] | undefined;
    scenes[sceneId] = {
      ...(current ?? { tts: {}, timing: missing, layer: null, clip: missing }),
      still: { state: 'fresh', cache_key: digest, artifact: { id, digest, cache_key: digest }, error_code: null },
    };
  });
  return { ...build, scenes };
}
