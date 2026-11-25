import type { Language } from '@/shared/api/client';
import { MOCK_STORY_LINES } from '@/shared/api/mock/story';

import type { ScriptDocument, ScriptScene, ScriptTarget } from './types';

/** Synthetic material only: the mock screen never reads user files. */
const DEFAULT_TOPIC = '커피를 고르는 세 가지 기준';
const TOPIC_IN_LINE = 60;

export function sceneEntityId(value: number): string {
  return `s_${String(value).padStart(26, '0')}`;
}

export function lineEntityId(value: number): string {
  return `l_${String(value).padStart(26, '0')}`;
}

function line(id: number, text: string) {
  return { id: lineEntityId(id), display_text: text, speech_text: text };
}

function topicLine(topic: string): string {
  const trimmed = topic.replace(/\s+/gu, ' ').trim().slice(0, TOPIC_IN_LINE);
  return `「${trimmed}」 이야기를 확인해요.`;
}

/** The line the draft adds after a one-line opening, so the first scene has two lines as the story scenes do. */
const OPENING_LEAD = '하나씩 살펴봐요.';

/** The synthetic scenes after the user's first lines: the shared mock story from its second scene. */
const SYNTHETIC_TAIL = MOCK_STORY_LINES.slice(1);

/**
 * The user's lines open unchanged; the synthetic draft fills only the rest. A
 * one-line opening, such as the sentence the user sent, gets a second line.
 */
function seedTexts(topic: string, script: string | null): readonly (readonly string[])[] {
  const opening = script !== null && script.trim() !== '' ? script.split(/\r?\n/u) : [topicLine(topic)];
  return [opening.length < 2 ? [...opening, OPENING_LEAD] : opening, ...SYNTHETIC_TAIL];
}

const BEATS = ['훅', '첫 번째', '두 번째', '세 번째', '마무리'] as const;

function seedScenes(topic: string, script: string | null): ScriptScene[] {
  let lineNumber = 0;
  return seedTexts(topic, script).map((texts, index) => {
    const scene: ScriptScene = {
      id: sceneEntityId(index + 1),
      beat_id: `beat_${index + 1}`,
      beat_label: BEATS[index] ?? `장면 ${index + 1}`,
      lines: texts.map((text) => {
        lineNumber += 1;
        return line(lineNumber, text);
      }),
    };
    return scene;
  });
}

/**
 * A scene the scene count added. Its line is empty, so the screen shows a
 * placeholder and the confirmation gate waits for a real line.
 */
export function createAppendedScene(sceneId: string, lineId: string): ScriptScene {
  return {
    id: sceneId,
    beat_id: 'more',
    beat_label: '이어서',
    lines: [{ id: lineId, display_text: '', speech_text: '' }],
  };
}

export function createSyntheticDocument(
  language: Language,
  target: ScriptTarget = { id: null, topic: null, script: null },
): ScriptDocument {
  const topic = (target.topic ?? '').trim() || DEFAULT_TOPIC;
  const script = target.script !== null && target.script.trim() !== '' ? target.script : null;
  const scenes = seedScenes(topic, script);
  return {
    id: target.id ?? `v_${String(1).padStart(26, '0')}`,
    revision: 1,
    topic,
    stage: 'concept_confirmed',
    script: { title: topic, raw_text: script, source: script === null ? 'llm' : 'user' },
    register: 'friendly',
    target_duration_s: 30,
    scene_order: scenes.map((scene) => scene.id),
    scenes: Object.fromEntries(scenes.map((scene) => [scene.id, scene])),
    language,
  };
}
