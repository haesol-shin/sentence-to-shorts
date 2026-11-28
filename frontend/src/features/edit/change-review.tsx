import { useEffect, useRef, useState } from 'react';
import { Check, X } from 'lucide-react';

import { Button } from '@/components/Button/Button';
import { CloseButton } from '@/components/CloseButton/CloseButton';
import { Dialog } from '@/components/Dialog/Dialog';
import { Notice } from '@/components/Notice/Notice';
import { useLocale, type LocaleValue } from '@/shared/lib/i18n/locale';

import { artifactUrl, type CatalogItem, type ChangePlan } from './api';
import { CAPTION_FONT_PATH, CAPTION_MODE_PATH, CAPTION_POSITION_PATH } from './captions/model';
import { isAudioSettingsChange, type EditValue } from './edit-context';
import { breaksFlow, insertScene, sceneNumber, sceneVisualLabel, stillIsReady, type Line, type Video } from './model';
import { BGM_PATH, bgmGainLabel, VOICE_PATH } from './sound/model';

/**
 * A scene by its number and beat, never by its id. A scene the plan adds is
 * not in the video yet, so it takes the place the add gives it.
 */
function sceneLabel(video: Video | null, sceneId: string, plan: ChangePlan | null = null): string {
  const added = plan?.ops.find((op) => op.op === 'add_scene' && op.scene.id === sceneId);
  const addOp = added?.op === 'add_scene' ? added : null;
  const scene = video?.scenes[sceneId] ?? addOp?.scene;
  const number = addOp !== null && video !== null
    ? insertScene(video, addOp.after ?? '', addOp.scene).order.indexOf(sceneId) + 1
    : sceneNumber(video, sceneId);
  return [number > 0 ? `${number}.` : '', scene?.beat_label ?? ''].filter((part) => part !== '').join(' ');
}

function linesOf(value: unknown): Line[] | null {
  if (!Array.isArray(value)) return null;
  return value.every((line) => line !== null && typeof line === 'object' && 'display_text' in line)
    ? (value as Line[])
    : null;
}

function newLines(plan: ChangePlan): Array<{ sceneId: string; lines: Line[] }> {
  return plan.ops.flatMap((op) => {
    if (op.op === 'add_scene') return [{ sceneId: op.scene.id, lines: op.scene.lines }];
    if (op.op !== 'set') return [];
    const parts = op.path.split('/');
    const sceneId = parts[2];
    if (sceneId === undefined || parts[3] !== 'lines') return [];
    const lines = linesOf(op.value);
    return lines === null ? [] : [{ sceneId, lines }];
  });
}

function valueAtPath(document: unknown, path: string): unknown {
  let cursor = document as Record<string, unknown> | unknown[];
  for (const part of path.split('/').slice(1)) {
    if (cursor === null || typeof cursor !== 'object') return undefined;
    cursor = (cursor as Record<string, unknown>)[part] as typeof cursor;
  }
  return cursor;
}

type ChangedValue = { path: string; label: string; before: string; after: string };
type ReviewLocale = Pick<LocaleValue, 't' | 'language'>;

function namedValue(prefix: string, value: unknown, { t }: ReviewLocale): string {
  if (typeof value !== 'string') return t('audio.review.unknown');
  const key = `${prefix}.${value}`;
  const label = t(key);
  return label === key ? t('audio.review.unknown') : label;
}

const CAPTION_NAMED = [
  [CAPTION_MODE_PATH, 'audio.caption.mode'],
  [CAPTION_POSITION_PATH, 'audio.caption.position'],
] as const;

const BGM_FIELDS = [
  ['enabled', 'audio.bgm.switch'],
  ['mood', 'audio.bgm.mood'],
  ['entry', 'audio.bgm.track'],
  ['gain_db_x10', 'audio.bgm.gain'],
  ['ducking', 'audio.bgm.ducking'],
] as const;

function refId(value: unknown): string | null {
  const id = valueAtPath(value, '/id');
  return typeof id === 'string' && id !== '' ? id : null;
}

function catalogLabel(
  id: string | null,
  items: readonly Pick<CatalogItem, 'id' | 'label'>[],
  { t, language }: ReviewLocale,
  none: string,
): string {
  if (id === null) return t(none);
  const label = items.find((item) => item.id === id)?.label?.[language]?.trim();
  return label && label !== id ? label : t('audio.review.unknown');
}

function bgmValue(
  field: (typeof BGM_FIELDS)[number][0],
  value: unknown,
  edit: EditValue,
  locale: ReviewLocale,
): string {
  const { t } = locale;
  if (field === 'entry' && (typeof value === 'string' || value === null)) {
    return catalogLabel(value, edit.bgm, locale, 'audio.bgm.trackNone');
  }
  if (field === 'enabled' || field === 'ducking') {
    if (typeof value === 'boolean') return t(value ? 'audio.on' : 'audio.off');
  } else if (field === 'mood' && typeof value === 'string') {
    const key = `audio.mood.${value}`;
    const label = t(key);
    if (label !== key) return label;
  } else if (field === 'gain_db_x10' && typeof value === 'number') {
    return bgmGainLabel(t, value);
  }
  return t('audio.review.unknown');
}

function sceneValueRows(
  path: string, before: unknown, after: unknown, edit: EditValue, locale: ReviewLocale,
): ChangedValue[] | null {
  const { t } = locale;
  const field = /^\/scenes\/[^/]+\/visual\/(background_id|characters|sfx)$/.exec(path)?.[1];
  const row = (
    key: string, label: string, previous: unknown[], next: unknown[],
    format: (value: unknown) => string,
  ): ChangedValue[] => {
    if (previous.length === next.length && previous.every((value, index) => value === next[index])) return [];
    const display = (values: unknown[]) => values.length === 0
      ? t('edit.change.none')
      : values.map(format).join(', ');
    return [{ path: key, label: t(label), before: display(previous), after: display(next) }];
  };
  const values = (value: unknown, pointer: string) =>
    Array.isArray(value) ? value.map((item) => valueAtPath(item, pointer)) : [];

  switch (field) {
    case 'background_id':
      return row(path, 'edit.scene.background', [before], [after],
        (value) => sceneVisualLabel(t, 'background', value, edit.styleOptions?.backgrounds));
    case 'characters': {
      const positions = '/anchor';
      const expressions = '/expression_id';
      return [
        ...row(`${path}${positions}`, 'edit.scene.position', values(before, positions), values(after, positions),
          (value) => sceneVisualLabel(t, 'position', value)),
        ...row(`${path}${expressions}`, 'edit.scene.expression', values(before, expressions), values(after, expressions),
          (value) => sceneVisualLabel(t, 'expression', value, edit.styleOptions?.expressions)),
      ];
    }
    case 'sfx': {
      const idPath = '/sfx_id/id';
      return row(path, 'edit.scene.sfx', values(before, idPath), values(after, idPath), (id) => {
        const label = edit.sfx.find((entry) => entry.id === id)?.label[locale.language];
        return label ?? sceneVisualLabel(t, 'sfx', id);
      });
    }
    default:
      return null;
  }
}

function changedValues(edit: EditValue, plan: ChangePlan, locale: ReviewLocale): ChangedValue[] {
  const { t } = locale;
  return plan.ops.flatMap((op) => {
    if (op.op !== 'set' || op.path.endsWith('/lines')) return [];
    if (op.path === VOICE_PATH || op.path.startsWith(`${VOICE_PATH}/`)) {
      const before = refId(valueAtPath(edit.video, VOICE_PATH));
      let after = before;
      if (op.path === VOICE_PATH) after = refId(op.value);
      if (op.path === `${VOICE_PATH}/id` && typeof op.value === 'string') after = op.value;
      if (before === after) return [];
      return [{
        path: VOICE_PATH,
        label: t('audio.voice.title'),
        before: catalogLabel(before, edit.voices, locale, 'audio.voice.none'),
        after: catalogLabel(after, edit.voices, locale, 'audio.voice.none'),
      }];
    }
    if (op.path === BGM_PATH || op.path.startsWith(`${BGM_PATH}/`)) {
      return BGM_FIELDS.flatMap(([field, label]) => {
        const path = `${BGM_PATH}/${field}`;
        const oldValue = valueAtPath(edit.video, path);
        const before = field === 'entry' ? refId(oldValue) : oldValue;
        let after: unknown;
        if (op.path === BGM_PATH || op.path === path) {
          const next = op.path === path ? op.value : valueAtPath(op.value, `/${field}`);
          after = field === 'entry' ? refId(next) : next;
        } else if (field === 'entry' && op.path === `${path}/id` && typeof op.value === 'string') {
          after = op.value;
        } else {
          return [];
        }
        return before === after ? [] : [{
          path,
          label: t(label),
          before: bgmValue(field, before, edit, locale),
          after: bgmValue(field, after, edit, locale),
        }];
      });
    }
    for (const [path, prefix] of CAPTION_NAMED) {
      if (op.path !== path) continue;
      const before = valueAtPath(edit.video, path);
      if (before === op.value) return [];
      return [{
        path,
        label: t(prefix),
        before: namedValue(prefix, before, locale),
        after: namedValue(prefix, op.value, locale),
      }];
    }
    if (op.path === CAPTION_FONT_PATH || op.path === `${CAPTION_FONT_PATH}/id`) {
      const before = refId(valueAtPath(edit.video, CAPTION_FONT_PATH));
      const after = op.path === CAPTION_FONT_PATH
        ? refId(op.value)
        : (typeof op.value === 'string' ? op.value : null);
      if (before === after) return [];
      return [{
        path: CAPTION_FONT_PATH,
        label: t('audio.caption.font'),
        before: catalogLabel(before, edit.fonts, locale, 'audio.caption.fontNone'),
        after: catalogLabel(after, edit.fonts, locale, 'audio.caption.fontNone'),
      }];
    }
    if (op.path.startsWith('/scenes/')) {
      const rows = sceneValueRows(op.path, valueAtPath(edit.video, op.path), op.value, edit, locale);
      if (rows !== null && rows.length > 0) return rows;
    }
    return [{ path: op.path, label: t('audio.review.generic'), before: '', after: '' }];
  });
}

function OrderComparison({ video, order }: { video: Video; order: readonly string[] }) {
  const { t } = useLocale();
  return (
    <>
      <div data-slot="order-compare" className="flex flex-col gap-2 text-[15px]">
        <p className="font-bold text-[var(--text-strong)]">{t('edit.change.compareOrder')}</p>
        <p>
          <span className="font-bold">{t('edit.change.oldOrder')}</span>{' '}
          {video.scene_order.map((id) => sceneLabel(video, id)).join(' → ')}
        </p>
        <p>
          <span className="font-bold">{t('edit.change.newOrder')}</span>{' '}
          {order.map((id) => sceneLabel(video, id)).join(' → ')}
        </p>
      </div>
      {breaksFlow(video, order) ? <Notice tone="warning">{t('edit.change.warningFlow')}</Notice> : null}
    </>
  );
}

function PendingBody({
  edit,
  plan,
  removed,
  previewNeeded,
  renderScenes,
  reviewSceneChange,
  imageFailed,
  onLoaded,
  onFailed,
}: {
  edit: EditValue;
  plan: ChangePlan;
  removed: ReadonlySet<string>;
  renderScenes: readonly string[];
  reviewSceneChange: boolean;
  previewNeeded: boolean;
  imageFailed: boolean;
  onLoaded: (sceneId: string) => void;
  onFailed: (sceneId: string) => void;
}) {
  const locale = useLocale();
  const { t } = locale;
  const newTexts = newLines(plan);
  const values = changedValues(edit, plan, locale);
  const opScenes = plan.ops.flatMap((op) => {
    if (op.op === 'add_scene') return [op.scene.id];
    if (op.op === 'remove_scene') return [op.scene_id];
    if (op.op === 'set' && op.path.startsWith('/scenes/')) return [op.path.split('/')[2] ?? ''];
    return [];
  });
  const scenes = [
    ...new Set([
      ...renderScenes,
      ...plan.effects.scene_ids_text,
      ...opScenes.filter((id) => id !== ''),
    ]),
  ];
  const preview = edit.pendingPreview;
  const reorder = plan.ops.find((op) => op.op === 'reorder');
  const labels = (ids: readonly string[]) =>
    ids.length === 0 ? t('edit.change.none') : ids.map((id) => sceneLabel(edit.video, id, plan)).join(', ');

  return (
    <div data-slot="change-review" className="flex flex-col gap-4">
      {newTexts.map(({ sceneId, lines }) => {
        const before = edit.video?.scenes[sceneId]?.lines ?? [];
        const added = plan.ops.find((op) => op.op === 'add_scene' && op.scene.id === sceneId);
        const copied = added?.op === 'add_scene' ? added.after : null;
        return (
          <div key={sceneId} data-slot="text-compare" className="flex flex-col gap-2">
            <p className="text-[15px] font-bold text-[var(--text-strong)]">{sceneLabel(edit.video, sceneId, plan)}</p>
            <div className="grid grid-cols-2 gap-2 text-[15px]">
              <div className="rounded-[var(--radius-panel)] bg-[var(--surface-muted)] p-2">
                <p className="text-[13px] text-[var(--text-muted)]">{t('edit.change.before')}</p>
                {added === undefined ? (
                  before.map((line) => <p key={line.id}>{line.display_text}</p>)
                ) : (
                  <p className="text-[var(--text-muted)]">
                    {copied === null
                      ? t('edit.change.addBlank')
                      : t('edit.change.addBody', { number: sceneNumber(edit.video, copied) })}
                  </p>
                )}
              </div>
              <div className="rounded-[var(--radius-panel)] bg-[var(--surface-muted)] p-2">
                <p className="text-[13px] text-[var(--text-muted)]">{t('edit.change.after')}</p>
                {lines.map((line) => <p key={line.id}>{line.display_text}</p>)}
              </div>
            </div>
          </div>
        );
      })}

      {[...removed].map((sceneId) => {
        const before = edit.video?.scenes[sceneId]?.lines ?? [];
        return (
          <div key={sceneId} data-slot="text-compare" className="flex flex-col gap-2">
            <p className="text-[15px] font-bold text-[var(--text-strong)]">{sceneLabel(edit.video, sceneId)}</p>
            <div className="grid grid-cols-2 gap-2 text-[15px]">
              <div className="rounded-[var(--radius-panel)] bg-[var(--surface-muted)] p-2">
                <p className="text-[13px] text-[var(--text-muted)]">{t('edit.change.before')}</p>
                {before.map((line) => <p key={line.id}>{line.display_text}</p>)}
              </div>
              <div className="rounded-[var(--radius-panel)] bg-[var(--surface-muted)] p-2">
                <p className="text-[13px] text-[var(--text-muted)]">{t('edit.change.after')}</p>
                <p>{t('edit.change.none')}</p>
              </div>
            </div>
          </div>
        );
      })}

      {reorder === undefined || edit.video === null ? null : (
        <OrderComparison video={edit.video} order={reorder.order} />
      )}

      {values.length === 0 ? null : (
        <ul className="flex flex-col gap-1 text-[15px]">
          {values.map((value) => (
            <li key={value.path} className="flex justify-between gap-2 rounded-[var(--radius-row)] bg-[var(--surface-muted)] px-3 py-2">
              <span className="min-w-0 truncate text-[var(--text-muted)]">{value.label}</span>
              {value.before === '' && value.after === '' ? null : (
                <>
                  <span className="min-w-0 break-words text-[var(--text-muted)]">{value.before} → </span>
                  <span className="min-w-0 break-words font-bold text-[var(--text-strong)]">{value.after}</span>
                </>
              )}
            </li>
          ))}
        </ul>
      )}

      {reviewSceneChange && (previewNeeded || removed.size > 0) ? (
      <div data-slot="still-compare" className="flex flex-col gap-2">
        <p className="text-[15px] font-bold text-[var(--text-strong)]">{t('edit.change.preview')}</p>
        {preview.loading ? (
          <p className="flex items-center gap-2 text-[15px] text-[var(--text-muted)]">
            <span className="spinner" aria-hidden="true" />
            {t('edit.change.previewLoading')}
          </p>
        ) : preview.error !== null ? (
          <Notice tone="warning">{t(preview.error)}</Notice>
        ) : (
          <div className="grid grid-cols-2 gap-2">
            {scenes.map((sceneId) => {
              const oldStill = stillIsReady(edit.build, sceneId) ? edit.build?.scenes[sceneId]?.still.artifact : null;
              const nextStill = removed.has(sceneId) ? undefined : preview.stills[sceneId];
              return (
                <div key={sceneId} className="flex flex-col gap-1 text-[13px] text-[var(--text-muted)]">
                  <span className="truncate">{sceneLabel(edit.video, sceneId, plan)}</span>
                  <div className="grid grid-cols-2 gap-1">
                    <span className="flex aspect-[9/16] items-center justify-center overflow-hidden rounded-[var(--radius-content)] bg-[var(--surface-sunken)]">
                      {oldStill === null || oldStill === undefined ? t('edit.change.beforeEmpty') : (
                        <img src={artifactUrl(oldStill.id)} alt="" className="h-full w-full object-cover" />
                      )}
                    </span>
                    <span className="flex aspect-[9/16] items-center justify-center overflow-hidden rounded-[var(--radius-content)] bg-[var(--surface-sunken)]">
                      {removed.has(sceneId) ? t('edit.change.removedStill') : nextStill === undefined ? t('edit.change.afterEmpty') : (
                        <img
                          data-slot="preview-after"
                          src={artifactUrl(nextStill)}
                          alt=""
                          onLoad={() => onLoaded(sceneId)}
                          onError={() => onFailed(sceneId)}
                          className="h-full w-full object-cover"
                        />
                      )}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
      ) : null}

      {previewNeeded && !edit.canPreviewChange ? (
        <Notice>{t('edit.change.previewAfterScript')}</Notice>
      ) : null}
      {imageFailed ? (
        <Notice tone="warning">{t('edit.change.previewFailed')}</Notice>
      ) : null}

      {reviewSceneChange ? (
        <div data-slot="rebuild-scope" className="flex flex-col gap-1 text-[15px]">
          <p className="font-bold">{t('edit.change.scope')}</p>
          {renderScenes.length > 0 ? <p>{t('edit.change.scopeScene', { scenes: labels(renderScenes) })}</p> : null}
          {plan.effects.scene_ids_text.length > 0 ? <p>{t('edit.change.scopeText', { scenes: labels(plan.effects.scene_ids_text) })}</p> : null}
          {plan.effects.scene_ids_tts.length > 0 ? <p>{t('edit.change.scopeTts', { scenes: labels(plan.effects.scene_ids_tts) })}</p> : null}
          {plan.effects.assemble ? <p>{t('edit.change.scopeAssemble')}</p> : null}
        </div>
      ) : null}

      {plan.warnings.length === 0 ? null : (
        <Notice tone="warning">
          {plan.warnings.map((warning, index) => (
            <span key={`${warning.code}-${index}`} className="block">
              {warning.code === 'story_order_broken'
                ? t('edit.change.warningFlow')
                : t('edit.change.warningAdjacent', {
                    scenes: warning.scene_id === null ? '' : sceneLabel(edit.video, warning.scene_id, plan),
                  })}
            </span>
          ))}
        </Notice>
      )}
    </div>
  );
}

/**
 * The review opens from a control that has no trigger relationship with the
 * dialog, so the window cannot return focus on its own. This remembers the
 * last focused control at open and focuses it again once the window is gone.
 */
let lastOutsideFocus: HTMLElement | null = null;
document.addEventListener('focusin', (event) => {
  const target = event.target;
  if (target instanceof HTMLElement && target.closest('[role="dialog"]') === null) lastOutsideFocus = target;
});

function useReturnFocus(): void {
  // A control that disables itself while it saves has already dropped focus to the page.
  const [origin] = useState(() =>
    document.activeElement instanceof HTMLElement && document.activeElement !== document.body
      ? document.activeElement
      : lastOutsideFocus,
  );
  useEffect(() => () => {
    // The control stays disabled while the review is open and for a moment after it closes.
    let tries = 0;
    const restore = () => {
      if (document.querySelector('[role="dialog"]') !== null) return;
      if (origin === null || origin === document.body || !origin.isConnected) return;
      origin.focus();
      tries += 1;
      if (document.activeElement !== origin && tries < 40) window.setTimeout(restore, 50);
    };
    window.setTimeout(restore, 0);
  }, [origin]);
}

function PlanReview({ edit, plan }: { edit: EditValue; plan: ChangePlan }) {
  const { t } = useLocale();
  useReturnFocus();
  const removed = new Set(plan.ops.flatMap((op) => op.op === 'remove_scene' ? [op.scene_id] : []));
  const audioOnly = isAudioSettingsChange(plan.ops);
  const renderScenes = audioOnly ? [] : plan.effects.scene_ids_render.filter((id) => !removed.has(id));
  const previewNeeded = renderScenes.length > 0;
  const started = useRef(false);
  const [loadedStills, setLoadedStills] = useState<Record<string, boolean>>({});
  const [failedStills, setFailedStills] = useState<Record<string, boolean>>({});

  useEffect(() => {
    if (started.current || !previewNeeded || !edit.canPreviewChange) return;
    started.current = true;
    edit.startPreview();
  }, [edit, previewNeeded]);

  const kind = plan.ops[0]?.op;
  const settingsOnly = plan.ops.length > 0 && plan.ops.every((op) => op.op === 'set' && op.path.startsWith('/settings/'));
  const reviewSceneChange = previewNeeded || !settingsOnly;
  const preview = edit.pendingPreview;
  const imageFailed = renderScenes.some((id) =>
    failedStills[id] === true || (preview.job?.state === 'succeeded' && preview.stills[id] === undefined),
  );
  const canApply = !previewNeeded || (
    edit.canPreviewChange && !preview.loading && preview.error === null && !imageFailed &&
    renderScenes.every((id) => preview.stills[id] !== undefined && loadedStills[id] === true)
  );
  const title =
    kind === 'reorder'
      ? t('edit.change.reorderTitle')
      : kind === 'add_scene'
        ? t('edit.change.addTitle')
        : kind === 'remove_scene'
          ? t('edit.change.deleteTitle')
          : t(reviewSceneChange ? 'edit.change.editTitle' : 'edit.change.settingsTitle');

  return (
    <Dialog
      open
      onOpenChange={(next) => {
        if (!next) edit.rejectPending();
      }}
      title={title}
      description={t(reviewSceneChange ? 'edit.change.description' : 'edit.change.settingsDescription')}
      label={title}
      actions={
        <>
          <Button variant="ghost" disabled={edit.busy} iconStart={<X aria-hidden size={16} />} onClick={edit.rejectPending}>
            {t('edit.change.reject')}
          </Button>
          <Button disabled={edit.busy || !canApply} iconStart={<Check aria-hidden size={16} />} onClick={edit.applyPending}>
            {t('edit.change.apply')}
          </Button>
        </>
      }
    >
      {edit.actionError === null ? null : (
        <div className="flex items-start gap-2">
          <Notice tone="error">{t(edit.actionError)}</Notice>
          <CloseButton label={t('edit.error.dismiss')} onClick={edit.dismissError} />
        </div>
      )}
      <PendingBody
        edit={edit}
        plan={plan}
        removed={removed}
        previewNeeded={previewNeeded}
        renderScenes={renderScenes}
        reviewSceneChange={reviewSceneChange}
        imageFailed={imageFailed}
        onLoaded={(sceneId) => setLoadedStills((current) => ({ ...current, [sceneId]: true }))}
        onFailed={(sceneId) => setFailedStills((current) => ({ ...current, [sceneId]: true }))}
      />
    </Dialog>
  );
}

export function ChangeReview({ edit }: { edit: EditValue }) {
  const { t } = useLocale();
  if (edit.pending !== null) return <PlanReview key={edit.pending.id} edit={edit} plan={edit.pending} />;
  if (edit.reorder === null || edit.video === null) return null;

  const title = t('edit.change.reorderTitle');
  return (
    <Dialog
      open
      onOpenChange={(next) => { if (!next) edit.dismissReorder(); }}
      title={title}
      description={t('edit.change.description')}
      label={title}
      actions={
        <>
          <Button variant="ghost" iconStart={<X aria-hidden size={16} />} onClick={edit.dismissReorder}>{t('edit.change.reject')}</Button>
          <Button iconStart={<Check aria-hidden size={16} />} onClick={edit.confirmReorder}>{t('edit.change.apply')}</Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <OrderComparison video={edit.video} order={edit.reorder.order} />
        <div data-slot="rebuild-scope" className="flex flex-col gap-1 text-[15px]">
          <p className="font-bold">{t('edit.change.scope')}</p>
          <p>{t('edit.change.scopeAssemble')}</p>
        </div>
      </div>
    </Dialog>
  );
}
