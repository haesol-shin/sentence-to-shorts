import { useEffect, useRef, useState } from 'react';

import { Button } from '@/components/Button/Button';
import { CloseButton } from '@/components/CloseButton/CloseButton';
import { Dialog } from '@/components/Dialog/Dialog';
import { Notice } from '@/components/Notice/Notice';
import { useLocale } from '@/shared/lib/i18n/locale';

import { artifactUrl, type ChangePlan } from './api';
import type { EditValue } from './edit-context';
import { breaksFlow, sceneNumber, stillIsReady, type Line, type Video } from './model';

function sceneLabel(video: Video | null, sceneId: string): string {
  const number = sceneNumber(video, sceneId);
  const scene = video?.scenes[sceneId];
  return `${number > 0 ? `${number}. ` : ''}${scene?.beat_label ?? sceneId}`;
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

function displayValue(value: unknown): string {
  return typeof value === 'string' ? value : JSON.stringify(value);
}

function changedValues(video: Video | null, plan: ChangePlan): Array<{ path: string; before: string; after: string }> {
  return plan.ops.flatMap((op) => {
    if (op.op !== 'set') return [];
    if (op.path.endsWith('/lines')) return [];
    return [{
      path: op.path.split('/').slice(2).join('/'),
      before: displayValue(valueAtPath(video, op.path)),
      after: displayValue(op.value),
    }];
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
  imageFailed,
  onLoaded,
  onFailed,
}: {
  edit: EditValue;
  plan: ChangePlan;
  removed: ReadonlySet<string>;
  previewNeeded: boolean;
  imageFailed: boolean;
  onLoaded: (sceneId: string) => void;
  onFailed: (sceneId: string) => void;
}) {
  const { t } = useLocale();
  const newTexts = newLines(plan);
  const values = changedValues(edit.video, plan);
  const opScenes = plan.ops.flatMap((op) => {
    if (op.op === 'add_scene') return [op.scene.id];
    if (op.op === 'remove_scene') return [op.scene_id];
    if (op.op === 'set') return [op.path.split('/')[2] ?? ''];
    return [];
  });
  const scenes = [
    ...new Set([
      ...plan.effects.scene_ids_render,
      ...plan.effects.scene_ids_text,
      ...opScenes.filter((id) => id !== ''),
    ]),
  ];
  const preview = edit.pendingPreview;
  const reorder = plan.ops.find((op) => op.op === 'reorder');
  const labels = (ids: readonly string[]) =>
    ids.length === 0 ? t('edit.change.none') : ids.map((id) => sceneLabel(edit.video, id)).join(', ');

  return (
    <div data-slot="change-review" className="flex flex-col gap-4">
      {newTexts.map(({ sceneId, lines }) => {
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
              <span className="min-w-0 truncate text-[var(--text-muted)]">{value.path}</span>
              <span className="shrink-0 text-[var(--text-muted)]">{value.before} → </span>
              <span className="shrink-0 font-bold text-[var(--text-strong)]">{value.after}</span>
            </li>
          ))}
        </ul>
      )}

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
                  <span className="truncate">{sceneLabel(edit.video, sceneId)}</span>
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

      {previewNeeded && !edit.canPreviewChange ? (
        <Notice>{t('edit.change.previewAfterScript')}</Notice>
      ) : null}
      {imageFailed ? (
        <Notice tone="warning">{t('edit.change.previewFailed')}</Notice>
      ) : null}

      <div data-slot="rebuild-scope" className="flex flex-col gap-1 text-[15px]">
        <p className="font-bold">{t('edit.change.scope')}</p>
        <p>{t('edit.change.scopeScene', { scenes: labels(plan.effects.scene_ids_render) })}</p>
        <p>{t('edit.change.scopeText', { scenes: labels(plan.effects.scene_ids_text) })}</p>
        <p>{t('edit.change.scopeTts', { scenes: labels(plan.effects.scene_ids_tts) })}</p>
        {plan.effects.assemble ? <p>{t('edit.change.scopeAssemble')}</p> : null}
      </div>

      {plan.warnings.length === 0 ? null : (
        <Notice tone="warning">
          {plan.warnings.map((warning, index) => (
            <span key={`${warning.code}-${index}`} className="block">
              {warning.code === 'story_order_broken'
                ? t('edit.change.warningFlow')
                : t('edit.change.warningAdjacent', {
                    scenes: warning.scene_id === null ? '' : sceneLabel(edit.video, warning.scene_id),
                  })}
            </span>
          ))}
        </Notice>
      )}
    </div>
  );
}

function PlanReview({ edit, plan }: { edit: EditValue; plan: ChangePlan }) {
  const { t } = useLocale();
  const removed = new Set(plan.ops.flatMap((op) => op.op === 'remove_scene' ? [op.scene_id] : []));
  const renderScenes = plan.effects.scene_ids_render.filter((id) => !removed.has(id));
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
          : t('edit.change.editTitle');

  return (
    <Dialog
      open
      onOpenChange={(next) => {
        if (!next) edit.rejectPending();
      }}
      title={title}
      description={t('edit.change.description')}
      label={title}
      actions={
        <>
          <Button variant="ghost" disabled={edit.busy} onClick={edit.rejectPending}>
            {t('edit.change.reject')}
          </Button>
          <Button disabled={edit.busy || !canApply} onClick={edit.applyPending}>
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
          <Button variant="ghost" onClick={edit.dismissReorder}>{t('edit.change.reject')}</Button>
          <Button onClick={edit.confirmReorder}>{t('edit.change.apply')}</Button>
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
