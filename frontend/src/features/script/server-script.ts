import {
  applyVideoChange,
  confirmVideoScript,
  newIdempotencyKey,
  readVideo,
  submitVideoChange,
  type Video,
} from '@/shared/api/client';
import type { components } from '@/shared/api/generated/openapi';

import { ScriptApiError } from './api';
import { isConfirmed } from './model';
import type { ScriptDocument, ScriptTarget } from './types';

type Scene = components['schemas']['Scene'];
type ChangeRequest = components['schemas']['ChangeRequest'];

function fromVideo(video: Video, sessionId: string): ScriptDocument {
  if (video.script === null || video.scene_order.length === 0) {
    throw new ScriptApiError('script_missing', 'The draft has no script');
  }
  const scenes = Object.fromEntries(video.scene_order.map((id) => {
    const { beat_id, beat_label, lines } = video.scenes[id];
    return [id, {
      id, beat_id, beat_label,
      lines: lines.map(({ id: lineId, display_text, speech_text }) => ({
        id: lineId, display_text, speech_text,
      })),
    }];
  }));
  return {
    id: sessionId,
    revision: video.revision,
    topic: video.topic,
    stage: video.stage,
    script: video.script,
    register: video.settings.format.register,
    target_duration_s: video.settings.target_duration_s,
    scene_order: video.scene_order,
    scenes,
    language: video.settings.language,
  };
}

/** Compare only what Script owns; Edit may have saved visuals in the meantime. */
function scriptContent(document: ScriptDocument): string {
  const { source, raw_text, title } = document.script;
  return JSON.stringify([source, raw_text, title, document.scene_order.map((id) => {
    const scene = document.scenes[id];
    return [id, scene.beat_id, scene.beat_label,
      scene.lines.map((line) => [line.id, line.display_text, line.speech_text])];
  })]);
}

function toServerScenes(document: ScriptDocument, head: Video): Scene[] {
  return document.scene_order.map((id) => {
    const scene = document.scenes[id];
    const existing = head.scenes[id];
    const lines = scene.lines.map((line) => {
      const previous = existing?.lines.find((entry) => entry.id === line.id);
      return {
        ...previous,
        ...line,
        speaker: previous?.speaker ?? 'narrator',
        highlight: previous?.display_text === line.display_text ? previous.highlight : [],
      };
    });
    const visual = existing?.visual ?? null;
    const lineIds = new Set(lines.map((line) => line.id));
    return {
      ...scene,
      lines,
      visual: visual === null ? null : {
        ...visual,
        elements: visual.elements.filter((element) =>
          element.reveal_line_id === null || lineIds.has(element.reveal_line_id)),
        sfx: visual.sfx.filter((cue) => lineIds.has(cue.line_id)),
      },
    };
  });
}

/** The draft job has applied before opening; this session keeps its own edits until confirmed. */
export async function openServerScript(videoId: string, target: ScriptTarget) {
  const initial = (await readVideo(videoId)).video;
  const draft = fromVideo(initial, target.id ?? videoId);
  let document = draft;
  const firstId = draft.scene_order[0];
  const firstScene = draft.scenes[firstId];
  const original = target.script;
  if (original !== null && original.trim() !== '') {
    document = {
      ...draft,
      script: { ...draft.script, source: 'user', raw_text: original },
      scenes: { ...draft.scenes, [firstId]: {
        ...firstScene,
        lines: [{ id: firstScene.lines[0].id, display_text: original, speech_text: original }],
      } },
    };
  }

  let known = draft;
  let knownSceneCount = initial.settings.format.scene_count;
  let pending: { document: ScriptDocument; baseRevision: number; key: string } | null = null;

  const confirm = async (next: ScriptDocument): Promise<ScriptDocument> => {
    const head = (await readVideo(videoId)).video;
    const current = fromVideo(head, next.id);
    const currentContent = scriptContent(current);
    const currentCount = head.settings.format.scene_count;
    const matches = (saved: ScriptDocument, count: number) =>
      current.register === saved.register &&
      current.target_duration_s === saved.target_duration_s &&
      currentCount === count && currentContent === scriptContent(saved);

    // Recover a save whose response was lost, but never overwrite other script edits.
    if (!matches(known, knownSceneCount) &&
        (pending === null || !matches(pending.document, pending.document.scene_order.length))) {
      throw new ScriptApiError('revision_conflict', 'The script changed on the server');
    }
    known = current;
    knownSceneCount = currentCount;

    const ops: ChangeRequest['ops'] = [];
    if (next.target_duration_s !== current.target_duration_s) {
      ops.push({ op: 'set', path: '/settings/target_duration_s', value: next.target_duration_s, origin: 'user' });
    }
    if (next.register !== current.register) {
      ops.push({ op: 'set', path: '/settings/format/register', value: next.register, origin: 'user' });
    }
    if (next.scene_order.length !== currentCount) {
      ops.push({ op: 'set', path: '/settings/format/scene_count', value: next.scene_order.length, origin: 'user' });
    }
    if (scriptContent(next) !== currentContent) {
      ops.push({ op: 'set_script', script: next.script, scenes: toServerScenes(next, head) });
    }

    let revision = current.revision;
    if (ops.length > 0) {
      if (pending?.document !== next || pending.baseRevision !== revision) {
        pending = { document: next, baseRevision: revision, key: newIdempotencyKey() };
      }
      const change = await submitVideoChange(videoId, {
        base_revision: revision,
        source: 'direct',
        target: { scene_id: null, pointer: null },
        ops,
      }, pending.key);
      if (change.status === 'proposed' && change.requires_confirmation) {
        // The footer press confirms this exact script and its plan; there is no preview request.
        revision = (await applyVideoChange(change.id, revision)).revision;
      } else if (change.status === 'applied' && change.applied_revision !== null) {
        revision = change.applied_revision;
      } else {
        throw new ScriptApiError('revision_conflict', 'The script change was not applied');
      }
      known = next;
      knownSceneCount = next.scene_order.length;
    }
    pending = null;

    const confirmed = await confirmVideoScript(videoId, revision);
    if (!isConfirmed(confirmed)) {
      throw new ScriptApiError('script_not_confirmed', 'The server did not confirm the script');
    }
    return { ...next, revision: confirmed.revision, stage: confirmed.stage };
  };

  return { document, confirm };
}
