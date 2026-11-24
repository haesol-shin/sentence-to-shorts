import type { Video } from '../client';

/**
 * The synthetic story every mock screen shows: five scenes of a video about a
 * day without the internet, with the scene and line counts the design pictures
 * draw. The script draft and the edit, result and making screens read the same
 * lines, so a screen compared with its picture differs in layout only.
 */
export const MOCK_STORY_LINES: readonly (readonly string[])[] = [
  ['인터넷이 하루 멈추면', '카드 결제가 안 돼요'],
  ['지도 앱도 멈추고', '길 찾기가 어려워요'],
  ['편의점에선 현금만 받아요', '현금이 없으면 못 사요', '줄이 길어져요'],
  ['메신저가 안 되니', '사람들이 직접 만나요'],
  ['하루가 지나면', '다시 연결돼요'],
];

/**
 * The recorded video with the story's lines. Each scene keeps its first line's
 * id, which its sound cues point at; the lines the story adds get fresh ids.
 */
export function withMockStory(video: Video): Video {
  const scenes = { ...video.scenes };
  video.scene_order.forEach((sceneId, sceneIndex) => {
    const scene = scenes[sceneId];
    const texts = MOCK_STORY_LINES[sceneIndex];
    if (scene === undefined || texts === undefined) return;
    const [first] = scene.lines;
    scenes[sceneId] = {
      ...scene,
      lines: texts.map((text, lineIndex) => ({
        speaker: first?.speaker ?? 'narrator',
        highlight: [],
        id: lineIndex === 0 && first !== undefined
          ? first.id
          : `l_0story${sceneIndex}${lineIndex}`.padEnd(28, '0'),
        display_text: text,
        speech_text: text,
      })),
    };
  });
  return { ...video, scenes };
}
