import { useState, type ReactNode } from 'react';
import { Music, Plus, Trash2 } from 'lucide-react';

import { Button } from '@/components/Button/Button';
import { Dialog, DialogClose } from '@/components/Dialog/Dialog';
import { EmptyState } from '@/components/EmptyState/EmptyState';
import { Notice } from '@/components/Notice/Notice';
import { ReorderList } from '@/components/ReorderList/ReorderList';
import { ScrollPane } from '@/components/ScrollPane/ScrollPane';
import { SettingsRow } from '@/components/SettingsRow/SettingsRow';
import { Tabs } from '@/components/Tabs/Tabs';
import { Tooltip } from '@/components/Tooltip/Tooltip';
import { CloseButton } from '@/components/CloseButton/CloseButton';
import { ValueField } from '@/components/ValueField/ValueField';
import { useLocale, type Translate } from '@/shared/lib/i18n/locale';
import { cn } from '@/shared/lib/utils';

import type { CatalogItem } from './api';
import { CaptionsTab } from './captions/captions-tab';
import { SoundTab } from './sound/sound-tab';
import { EDIT_TABS } from './tabs';
import type { EditValue, SceneBand, SceneFieldPatch } from './edit-context';
import {
  POSITION_CELLS,
  anchorForCell,
  cellForAnchor,
  estimatedSeconds,
  MAX_LINES_PER_SCENE,
  sceneNumber,
  sceneVisualLabel,
  spanSelected,
  toggleSpan,
  wordSpans,
  type BandField,
  type Line,
  type PlacementAnchor,
  type Scene,
  type Span,
} from './model';

function labelFor(t: Translate, prefix: string, id: string): string {
  const key = `${prefix}.${id}`;
  const label = t(key);
  return label === key ? id : label;
}

function sceneCharacters(scene: Scene) {
  return scene.visual?.characters ?? [];
}

/**
 * A cell a chat change touched: a light band crosses it once. A new band
 * token mounts it again, so a second change lights it a second time.
 */
function Swept({
  field,
  band,
  className,
  children,
}: {
  field: BandField;
  band: SceneBand | null;
  className?: string;
  children: ReactNode;
}) {
  const lit = band !== null && band.fields.includes(field);
  return (
    <div key={lit ? band.token : 'still'} className={cn('edit-sweep', className)} data-sweep={lit ? 'true' : undefined}>
      {children}
    </div>
  );
}

function PositionGrid({
  value,
  onChange,
  disabled = false,
}: {
  value: PlacementAnchor;
  onChange: (anchor: PlacementAnchor) => void;
  disabled?: boolean;
}) {
  const { t } = useLocale();
  const selected = cellForAnchor(value);
  return (
    <div
      data-slot="position-grid"
      role="group"
      aria-label={t('edit.scene.position')}
      className="grid grid-cols-3 gap-2"
    >
      {POSITION_CELLS.map((cell) => {
        const active = cell.row === selected.row && cell.column === selected.column;
        const anchor = anchorForCell(cell.row, cell.column);
        return (
          <button
            key={anchor}
            type="button"
            aria-label={sceneVisualLabel(t, 'position', anchor)}
            aria-pressed={active}
            data-anchor={anchor}
            disabled={disabled}
            onClick={() => onChange(anchor)}
            className={cn(
              'focus-ring relative flex size-11 items-center justify-center rounded-[var(--radius-inset)] border-2 transition-colors duration-[var(--motion-short)]',
              active
                ? 'border-[var(--ring)] bg-[var(--state-selected)]'
                : 'border-transparent bg-[var(--surface-muted)] hover:bg-[var(--state-hover-gray)]',
              disabled && 'cursor-not-allowed opacity-50 hover:bg-[var(--surface-muted)]',
            )}
          >
            <span
              aria-hidden="true"
              className={cn(
                'block rounded-[var(--radius-inset)]',
                active
                  ? 'size-[10px] bg-[var(--emphasis)]'
                  : 'size-[6px] bg-[var(--sub)]',
              )}
            />
          </button>
        );
      })}
    </div>
  );
}

function HighlightWords({
  scene,
  onChange,
}: {
  scene: Scene;
  onChange: (lineId: string, spans: Span[]) => void;
}) {
  const { t } = useLocale();
  if (scene.lines.length === 0) {
    return <p className="text-[15px] text-[var(--text-muted)]">{t('edit.scene.noLines')}</p>;
  }
  return (
    <div className="flex flex-col gap-3">
      {scene.lines.map((line, index) => (
        <div key={line.id} data-slot="highlight-line" className="flex flex-col gap-1">
          <span className="text-[13px] text-[var(--text-muted)]">
            {t('edit.scene.line', { number: index + 1 })}
          </span>
          <div className="flex min-h-11 flex-wrap items-center gap-1">
            {wordSpans(line.display_text).map((word) => {
              const active = spanSelected(line.highlight, word);
              return (
                <button
                  key={`${word.start}-${word.text}`}
                  type="button"
                  aria-pressed={active}
                  onClick={() => onChange(line.id, toggleSpan(line.highlight, word))}
                  className={cn(
                    'hit-area focus-ring min-h-11 rounded-[var(--radius-inset)] px-1 text-[17px] leading-6 transition-colors duration-[var(--motion-short)]',
                    active
                      ? 'bg-[var(--surface-muted)] text-[var(--emphasis)] underline decoration-2 underline-offset-2'
                      : 'text-[var(--text)] hover:bg-[var(--surface-muted)]',
                  )}
                >
                  {word.text}
                </button>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

function SfxPicker({
  open,
  onOpenChange,
  onAdd,
  disabled,
  items,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onAdd: (item: CatalogItem) => void;
  disabled: boolean;
  items: readonly CatalogItem[];
}) {
  const { t, language } = useLocale();
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={t('edit.sfx.title')}
      description={t('audio.sfx.rule')}
      label={t('edit.sfx.title')}
      actions={
        <DialogClose render={<Button variant="ghost">{t('edit.sfx.close')}</Button>} />
      }
    >
      <DialogClose
        render={
          <CloseButton
            label={t('edit.sfx.close')}
            data-slot="sfx-close"
            className="absolute top-4 right-4"
          />
        }
      />
      <ScrollPane label={t('edit.sfx.list')} jumpLabel={t('shell.scroll.jump')} className="max-h-72 min-h-0">
        <div className="flex flex-col">
          {items.length === 0 ? (
            <p className="px-3 py-2 text-[15px] text-[var(--text-muted)]">{t('edit.sfx.empty')}</p>
          ) : (
            items.map((item) => (
              <button
                key={item.id}
                type="button"
                disabled={disabled}
                onClick={() => onAdd(item)}
                className="focus-ring flex min-h-11 items-center justify-between rounded-[var(--radius-row)] px-3 text-left text-[15px] text-[var(--text)] hover:bg-[var(--surface-muted)] disabled:cursor-not-allowed disabled:text-[var(--text-disabled)]"
              >
                <span>{item.label[language]}</span>
                <Music aria-hidden size={16} className="text-[var(--text-muted)]" />
              </button>
            ))
          )}
        </div>
      </ScrollPane>
    </Dialog>
  );
}

/**
 * One caption box per line. The spoken text is not asked for: it follows the
 * caption, so the voice and the caption never drift apart.
 */
function LineEditor({
  line,
  index,
  sceneId,
  edit,
}: {
  line: Line;
  index: number;
  sceneId: string;
  edit: EditValue;
}) {
  const { t } = useLocale();
  const [display, setDisplay] = useState(line.display_text);
  const dirty = display !== line.display_text;
  const invalid = display.trim() === '';
  return (
    <div data-slot="line-editor" className="flex flex-col rounded-[var(--radius-content)] bg-[var(--surface-muted)] px-4 pt-2 pb-[10px]">
      <span className="text-[15px] leading-[18px] text-[var(--text-muted)]">{index + 1}</span>
      <textarea
        aria-label={t('edit.scene.displayTextLabel', { number: index + 1 })}
        value={display}
        onChange={(event) => setDisplay(event.target.value)}
        rows={1}
        className="w-full resize-none rounded-[var(--radius-inset)] bg-[var(--surface-muted)] text-[15px] leading-[18px] text-[var(--text-strong)] outline-none [field-sizing:content] focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
      />
      {/* The line keeps its one row until the text changes; saving is a step on its own. */}
      {dirty ? (
        <div className="mt-1 flex justify-end">
          <Button
            variant="ghost"
            disabled={invalid || edit.busy}
            onClick={() => edit.applyLine(sceneId, line.id, display, display)}
          >
            {t('edit.scene.saveLine')}
          </Button>
        </div>
      ) : null}
    </div>
  );
}

function SceneForm({ edit, scene }: { edit: EditValue; scene: Scene }) {
  const { t } = useLocale();
  const [pickerOpen, setPickerOpen] = useState(false);
  const number = sceneNumber(edit.video, scene.id);
  const character = sceneCharacters(scene)[0];
  const hasCharacter = sceneCharacters(scene).length > 0;
  const background = scene.visual?.background_id ?? '';
  const expression = character?.expression_id ?? '';
  const anchor = character?.anchor ?? 'center';
  const cues = scene.visual?.sfx ?? [];
  const backgrounds = edit.styleOptions?.backgrounds ?? [];
  const expressions = edit.styleOptions?.expressions ?? [];
  const backgroundIds = [...new Set([...(background ? [background] : []), ...backgrounds])];
  const expressionIds = [...new Set([...(expression ? [expression] : []), ...expressions])];
  const backgroundItems = backgroundIds.map((id) => ({
    value: id, label: sceneVisualLabel(t, 'background', id, backgrounds),
  }));
  const expressionItems = expressionIds.map((id) => ({
    value: id, label: sceneVisualLabel(t, 'expression', id, expressions),
  }));
  const moveItems = edit.scenes.map((_, index) => ({
    value: String(index),
    label: t('edit.scene.number', { number: index + 1 }),
  }));

  const apply = (patch: SceneFieldPatch) => edit.applyField(patch);
  const band = edit.band !== null && edit.band.sceneId === scene.id ? edit.band : null;

  return (
    <div data-slot="scene-form" className="flex flex-col gap-[18px]">
      <div className="flex flex-col gap-1.5">
        <h2 className="text-[22px] leading-[normal] font-bold text-[var(--text-strong)]">
          {t('edit.scene.number', { number })}
        </h2>
        <p className="text-[15px] leading-[normal] text-[var(--text-muted)]">{t('edit.scene.scope')}</p>
      </div>

      <Swept field="lines" band={band} className="flex flex-col gap-[10px]">
        <h3 className="flex items-baseline justify-between text-[17px] leading-[normal] font-bold text-[var(--text-strong)]">
          {t('edit.scene.lines')}
          <small className="text-[15px] font-normal text-[var(--text-muted)]">
            {t('edit.scene.lineCount', { count: scene.lines.length, max: MAX_LINES_PER_SCENE })}
          </small>
        </h3>
        {scene.lines.map((line, index) => (
          <LineEditor
            key={`${line.id}-${line.display_text}-${line.speech_text}`}
            line={line}
            index={index}
            sceneId={scene.id}
            edit={edit}
          />
        ))}
      </Swept>

      {/* Each value names itself inside its field, so the group title is the only row label. */}
      <Swept field="expression" band={band}>
        <SettingsRow
          className="edit-field-group"
          label={t('edit.scene.characterGroup')}
          control={
            <ValueField
              className="edit-scene-field"
              label={t('edit.scene.expression')}
              name={t('edit.scene.expression')}
              items={expressionItems}
              value={expression}
              disabled={!hasCharacter}
              onValueChange={(value) => apply({ kind: 'expression', value })}
            />
          }
        />
      </Swept>

      <Swept field="position" band={band}>
        <SettingsRow
          label={t('edit.scene.position')}
          description={hasCharacter ? t('edit.scene.positionHelp') : t('edit.scene.noCharacter')}
          control={
            <PositionGrid
              value={anchor}
              disabled={!hasCharacter}
              onChange={(next) => apply({ kind: 'position', anchor: next })}
            />
          }
        />
      </Swept>

      <Swept field="background" band={band}>
        <SettingsRow
          className="edit-field-group"
          label={t('edit.scene.backgroundGroup')}
          control={
            <ValueField
              className="edit-scene-field"
              label={t('edit.scene.background')}
              name={t('edit.scene.background')}
              items={backgroundItems}
              value={background}
              onValueChange={(value) => apply({ kind: 'background', value })}
            />
          }
        />
      </Swept>

      <Swept field="highlight" band={band} className="flex flex-col gap-2">
        <h3 className="text-[15px] font-bold text-[var(--text-strong)]">
          {t('edit.scene.highlight')}
        </h3>
        <HighlightWords
          scene={scene}
          onChange={(lineId, spans) => apply({ kind: 'highlight', lineId, spans })}
        />
      </Swept>

      <Swept field="sfx" band={band} className="flex flex-col gap-2">
        <div className="flex items-center justify-between gap-2">
          <h3 className="text-[15px] font-bold text-[var(--text-strong)]">
            {t('edit.scene.sfx')}
          </h3>
          <Button
            variant="ghost"
            disabled={cues.length >= 2 || edit.busy}
            onClick={() => setPickerOpen(true)}
            iconStart={<Plus aria-hidden size={16} />}
          >
            {t('edit.scene.sfxAdd')}
          </Button>
        </div>
        {cues.length === 0 ? (
          <p className="text-[15px] text-[var(--text-muted)]">{t('edit.scene.sfxEmpty')}</p>
        ) : (
          <ul className="flex flex-col gap-1">
            {cues.map((cue, index) => (
              <li
                key={`${cue.sfx_id.id}-${index}`}
                className="flex min-h-11 items-center justify-between gap-2 rounded-[var(--radius-row)] bg-[var(--surface-muted)] px-3 text-[15px]"
              >
                <span className="flex min-w-0 items-center gap-2">
                  <Music aria-hidden size={16} className="text-[var(--text-muted)]" />
                  <span className="truncate">{labelFor(t, 'edit.sfx.name', cue.sfx_id.id)}</span>
                </span>
                <button
                  type="button"
                  aria-label={t('edit.scene.sfxRemove', {
                    name: labelFor(t, 'edit.sfx.name', cue.sfx_id.id),
                  })}
                  onClick={() =>
                    apply({ kind: 'sfx', cues: cues.filter((entry) => entry !== cue) })
                  }
                  className="inline-flex size-11 items-center justify-center rounded-[var(--radius-pill)] text-[var(--text-muted)] hover:bg-[var(--surface-sunken)] hover:text-[var(--text-strong)]"
                >
                  <Trash2 aria-hidden size={16} />
                </button>
              </li>
            ))}
          </ul>
        )}
        <p className="text-[13px] text-[var(--text-muted)]">{t('edit.scene.sfxLimit')}</p>
      </Swept>

      <section className="flex flex-col gap-3">
        <h3 className="text-[15px] font-bold text-[var(--text-strong)]">
          {t('edit.scene.order')}
        </h3>
        <ReorderList
          label={t('edit.scene.order')}
          labels={{
            grip: (item) => t('edit.scene.reorderGrip', { label: item }),
            up: (item) => t('edit.scene.moveUp', { label: item }),
            down: (item) => t('edit.scene.moveDown', { label: item }),
          }}
          items={edit.scenes.map((item, index) => ({
            id: item.id,
            label: t('edit.scene.number', { number: index + 1 }),
          }))}
          onReorder={(items) => {
            edit.requestReorder(items.map((item) => item.id));
          }}
        />
        <SettingsRow
          label={t('edit.scene.moveTo')}
          control={
            <ValueField
              label={t('edit.scene.moveTo')}
              items={moveItems}
              value={String(Math.max(0, edit.scenes.findIndex((item) => item.id === scene.id)))}
              onValueChange={(value) => edit.requestReorderTo(scene.id, Number(value))}
            />
          }
        />
      </section>

      <div className="flex items-center justify-between gap-2 border-t border-[var(--border)] pt-4">
        <span className="text-[15px] text-[var(--text-muted)]">
          {t('edit.scene.estimated', { seconds: estimatedSeconds(scene) })}
        </span>
        <Button
          variant="ghost"
          onClick={() => edit.requestDelete(scene.id)}
          iconStart={<Trash2 aria-hidden size={16} />}
        >
          {t('edit.scene.delete')}
        </Button>
      </div>

      <SfxPicker
        open={pickerOpen}
        onOpenChange={setPickerOpen}
        disabled={cues.length >= 2}
        items={edit.sfx}
        onAdd={(item) => {
          if (cues.length >= 2) return;
          edit.addSfx(scene.id, item);
          setPickerOpen(false);
        }}
      />
    </div>
  );
}

export function ScenePanel({ edit }: { edit: EditValue }) {
  const { t } = useLocale();
  const tabItems = EDIT_TABS.map((tab) => ({ value: tab.value, label: t(tab.labelKey) }));

  if (edit.loading) {
    return (
      <div className="flex min-h-0 flex-1 items-center justify-center gap-2 text-[15px] text-[var(--text-muted)]">
        <span className="spinner" aria-hidden="true" />
        {t('edit.loading')}
      </div>
    );
  }

  if (edit.error !== null) {
    return (
      <div className="flex min-h-0 flex-1 flex-col gap-3">
        <Notice tone="error">{t(edit.error)}</Notice>
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4">
      {edit.actionError === null ? null : (
        <div className="flex items-start gap-2">
          <Notice tone="error">{t(edit.actionError)}</Notice>
          <CloseButton label={t('edit.error.dismiss')} onClick={edit.dismissError} />
        </div>
      )}
      <div className="flex items-center justify-between gap-2">
        <Tabs
          items={tabItems}
          label={t('edit.tabs.label')}
          value={edit.tab}
          onValueChange={edit.setTab}
          className="min-w-0 flex-1"
        />
        <Tooltip content={t('edit.preview.captionSaveReason')} side="bottom">
          <span tabIndex={0} className="inline-flex shrink-0" data-slot="caption-save">
            <Button variant="ghost" disabled>
              {t('edit.preview.captionSave')}
            </Button>
          </span>
        </Tooltip>
      </div>
      {edit.tab === 'sound' ? (
        <SoundTab edit={edit} />
      ) : edit.tab === 'captions' ? (
        <CaptionsTab edit={edit} />
      ) : edit.selectedScene === null ? (
        <EmptyState
          title={t('edit.scene.chooseTitle')}
          actions={
            <Button onClick={edit.requestAdd} iconStart={<Plus aria-hidden size={16} />}>
              {t('edit.scene.add')}
            </Button>
          }
        >
          {t('edit.scene.chooseBody')}
        </EmptyState>
      ) : (
        <ScrollPane label={t('edit.scene.form')} jumpLabel={t('shell.scroll.jump')} className="min-h-0 flex-1">
          <div className="pb-16">
            <SceneForm key={edit.selectedScene.id} edit={edit} scene={edit.selectedScene} />
          </div>
        </ScrollPane>
      )}
    </div>
  );
}
