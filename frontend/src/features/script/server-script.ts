import {
  applyVideoChange,
  cancelVideoJob,
  confirmVideoScript,
  getJson,
  newIdempotencyKey,
  readJob,
  readVideo,
  rejectVideoChange,
  submitScriptRebuild,
  submitVideoChange,
  submitVideoMessage,
  type Job,
  type Video,
} from '@/shared/api/client';
import type { components } from '@/shared/api/generated/openapi';

import { ScriptApiError, type ScriptApi } from './api';
import { isConfirmed } from './model';
import type { ScriptDocument, ScriptSettingsProposal, ScriptTarget } from './types';

type Scene = components['schemas']['Scene'];
type ChangeRequest = components['schemas']['ChangeRequest'];
type ChangePlan = components['schemas']['ChangePlan'];

async function finishStoryJob(job: Job, signal?: AbortSignal): Promise<Job> {
  let cancelled = false;
  while (job.state === 'queued' || job.state === 'running' || job.state === 'cancelling') {
    if (signal?.aborted && !cancelled && job.state !== 'cancelling') {
      cancelled = true;
      try {
        job = await cancelVideoJob(job.id);
        continue;
      } catch {
        // The job may have finished just before the cancellation request.
      }
    }
    await new Promise<void>((resolve) => setTimeout(resolve, 300));
    job = (await readJob(job.id, null)).job ?? job;
  }
  if (job.state === 'cancelled') throw new ScriptApiError('cancelled', 'The rewrite stopped');
  if (job.state !== 'succeeded') throw new ScriptApiError('script_invalid', 'The rewrite did not succeed');
  return job;
}

function texts(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((text): text is string => typeof text === 'string') : [];
}

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
  let pending: { document: ScriptDocument; count: number; baseRevision: number; key: string } | null = null;

  const structureOf = (document: ScriptDocument): string =>
    JSON.stringify(document.scene_order.map((id) => [id, document.scenes[id]?.lines.map((line) => line.id)]));

  /**
   * Adopt what the conversation changed on the server without dropping unsaved
   * lines: the server keeps its structure and settings, and the local text of
   * every line that still exists here stays. Structural edits made here are not
   * merged, so the next save reports the conflict instead of overwriting them.
   */
  const sync: NonNullable<ScriptApi['sync']> = async (next) => {
    const head = (await readVideo(videoId)).video;
    const server = fromVideo(head, next.id);
    if (structureOf(server) !== structureOf(known)) {
      throw new ScriptApiError('revision_conflict', 'The script changed on the server');
    }
    const merged: ScriptDocument = {
      ...server,
      scenes: Object.fromEntries(server.scene_order.map((id) => {
        const scene = server.scenes[id];
        const local = next.scenes[id];
        const lines = scene.lines.map((line) => {
          const edited = local?.lines.find((entry) => entry.id === line.id);
          return edited === undefined ? line : { ...line, display_text: edited.display_text, speech_text: edited.speech_text };
        });
        return [id, { ...scene, lines }];
      })),
    };
    known = server;
    knownSceneCount = head.settings.format.scene_count;
    pending = null;
    return merged;
  };

  const save = async (
    given: ScriptDocument,
    explicitCount?: number,
  ): Promise<{ revision: number; document: ScriptDocument }> => {
    const head = (await readVideo(videoId)).video;
    const current = fromVideo(head, given.id);
    const currentContent = scriptContent(current);
    const currentCount = head.settings.format.scene_count;
    const next = given;
    const count = explicitCount ?? (next.scene_order.length === known.scene_order.length
      ? knownSceneCount : next.scene_order.length);
    const matches = (saved: ScriptDocument, count: number) =>
      current.register === saved.register &&
      current.target_duration_s === saved.target_duration_s &&
      currentCount === count && currentContent === scriptContent(saved);

    // Recover a save whose response was lost, but never overwrite other script edits.
    if (!matches(known, knownSceneCount) &&
        (pending === null || !matches(pending.document, pending.count))) {
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
    if (count !== currentCount) {
      ops.push({ op: 'set', path: '/settings/format/scene_count', value: count, origin: 'user' });
    }
    if (scriptContent(next) !== currentContent) {
      ops.push({ op: 'set_script', script: next.script, scenes: toServerScenes(next, head) });
    }

    let revision = current.revision;
    if (ops.length > 0) {
      if (pending?.document !== next || pending.count !== count || pending.baseRevision !== revision) {
        pending = { document: next, count, baseRevision: revision, key: newIdempotencyKey() };
      }
      const change = await submitVideoChange(videoId, {
        base_revision: revision,
        source: 'direct',
        target: { scene_id: null, pointer: null },
        ops,
      }, pending.key);
      if (change.status === 'proposed' && change.requires_confirmation) {
        // This saves only the user's existing edits, not the model's proposal.
        revision = (await applyVideoChange(change.id, revision)).revision;
      } else if (change.status === 'applied' && change.applied_revision !== null) {
        revision = change.applied_revision;
      } else {
        throw new ScriptApiError('revision_conflict', 'The script change was not applied');
      }
      known = next;
      knownSceneCount = count;
    }
    pending = null;
    return { revision, document: next };
  };

  const confirm = async (next: ScriptDocument): Promise<ScriptDocument> => {
    const { revision, document: saved } = await save(next, next.scene_order.length);

    const confirmed = await confirmVideoScript(videoId, revision);
    if (!isConfirmed(confirmed)) {
      throw new ScriptApiError('script_not_confirmed', 'The server did not confirm the script');
    }
    return { ...saved, revision: confirmed.revision, stage: confirmed.stage };
  };

  const rewrite: ScriptApi['rewrite'] = async (next, sceneId, options) => {
    const { signal, instruction } = options ?? {};
    const stopped = new ScriptApiError('cancelled', 'The rewrite stopped');
    if (signal?.aborted) throw stopped;
    const { revision } = await save(next);
    if (signal?.aborted) throw stopped;
    const path = `/scenes/${sceneId}/lines`;
    const job = await finishStoryJob(await submitVideoMessage(videoId, {
      base_revision: revision, text: instruction ?? '', target: { scene_id: sceneId, pointer: path },
    }), signal);
    const result = job.result;
    const changeId = result?.change_id;
    if (typeof changeId !== 'string') {
      if (signal?.aborted) throw stopped;
      return { lines: null, unsupported: [...texts(result?.notes), ...texts(result?.unsupported)] };
    }
    const plan = await getJson<ChangePlan>(`/changes/${encodeURIComponent(changeId)}`);
    if (plan.status !== 'proposed') throw new ScriptApiError('revision_conflict', 'The rewrite is no longer proposed');
    // Script owns the draft. Release the server proposal and keep its candidate
    // locally so applying it never replaces other unsaved edits with a reread.
    await rejectVideoChange(plan.id);
    if (signal?.aborted) throw stopped;
    const op = plan.ops.find((item) => item.op === 'set' && item.path === path);
    const lines = op?.op === 'set' && Array.isArray(op.value) ? op.value as Scene['lines'] : null;
    const dropped = plan.ops.some((item) => item !== op);
    const droppedNote = next.language === 'ko'
      ? '장면 제목과 효과음 변경은 대본에서 적용하지 않아요. 편집 단계에서 바꿔 주세요.'
      : 'Scene titles and sound effects are not applied in the script. Change them in the edit step.';
    return {
      lines: lines?.map(({ id, display_text, speech_text }) => ({ id, display_text, speech_text })) ?? null,
      unsupported: [...texts(plan.notes), ...texts(plan.unsupported), ...(dropped ? [droppedNote] : [])],
    };
  };

  const rebuild = async (next: ScriptDocument, { duration, count }: ScriptSettingsProposal): Promise<ScriptDocument> => {
    const { revision } = await save({ ...next, target_duration_s: duration }, count);
    const job = await finishStoryJob(await submitScriptRebuild(videoId, revision));
    const changeId = job.result?.change_id;
    if (typeof changeId !== 'string') throw new ScriptApiError('script_invalid', 'Missing script proposal');
    const status = job.result?.status;
    if (status !== 'proposed' && status !== 'applied') {
      throw new ScriptApiError('revision_conflict', 'The script rewrite is stale');
    }
    const head = status === 'proposed'
      ? await applyVideoChange(changeId, revision)
      : (await readVideo(videoId)).video;
    known = fromVideo(head, next.id);
    knownSceneCount = head.settings.format.scene_count;
    return known;
  };

  return { document, confirm, rewrite, rebuild, sync };
}
