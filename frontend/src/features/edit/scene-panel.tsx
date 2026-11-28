import { useState, type ReactElement, type ReactNode } from 'react';
import { ChevronDown, Image, Music, Pencil, Trash2 } from 'lucide-react';

import { Button } from '@/components/Button/Button';
import { CloseButton } from '@/components/CloseButton/CloseButton';
import { Dialog, DialogClose } from '@/components/Dialog/Dialog';
import { EmptyState } from '@/components/EmptyState/EmptyState';
import { IconButton } from '@/components/IconButton/IconButton';
import { Notice } from '@/components/Notice/Notice';
import { ScrollPane } from '@/components/ScrollPane/ScrollPane';
import { SettingsRow } from '@/components/SettingsRow/SettingsRow';
import { Tabs, TabsPanel } from '@/components/Tabs/Tabs';
import { ValueField } from '@/components/ValueField/ValueField';
import { useLocale, type Translate } from '@/shared/lib/i18n/locale';
import { cn } from '@/shared/lib/utils';

import type { CatalogItem } from './api';
import type { EditValue, SceneBand, SceneFieldPatch } from './edit-context';
import {
  POSITION_CHOICES,
  MAX_LINES_PER_SCENE,
  sceneNumber,
  sceneVisualLabel,
  spanSelected,
  toggleSpan,
  wordSpans,
  type BandField,
  type Line,
  type Scene,
} from './model';
import { useAudioPreview } from './sound/use-audio-preview';
import { EDIT_TABS } from './tabs';
import { WholePanel } from './whole-panel';
import './scene-panel.css';

function labelFor(t: Translate, prefix: string, id: string): string {
  const key = `${prefix}.${id}`;
  const label = t(key);
  return label === key ? id : label;
}

/**
 * A cell a chat change touched: a light band crosses it once. A new band
 * token mounts it again, so a second change lights it a second time.
 */
function Swept({
  fields,
  band,
  className,
  children,
}: {
  fields: readonly BandField[];
  band: SceneBand | null;
  className?: string;
  children: ReactNode;
}) {
  const lit = band !== null && band.fields.some((field) => fields.includes(field));
  return (
    <div key={lit ? band.token : 'still'} className={cn('edit-sweep', className)} data-sweep={lit ? 'true' : undefined}>
      {children}
    </div>
  );
}

/** A value button that names itself inside, as the value fields of the panel do. */
function fieldContent(name: string, value: string) {
  return (
    <>
      <span className="field-trigger__name">{name}</span>
      <span className="field-trigger__value">{value}</span>
      <span className="field-trigger__icon">
        <ChevronDown aria-hidden />
      </span>
    </>
  );
}

function BackgroundPicker({
  current,
  items,
  onApply,
  container,
  trigger,
}: {
  current: string;
  items: readonly { value: string; label: string }[];
  onApply: (id: string) => void;
  container: HTMLElement | null;
  trigger: ReactElement;
}) {
  const { t } = useLocale();
  const [open, setOpen] = useState(false);
  const [choice, setChoice] = useState(current);
  return (
    <Dialog
      title={t('edit.scene.background')}
      description={t('edit.scene.backgroundHint')}
      open={open}
      onOpenChange={(next) => {
        if (next) setChoice(current);
        setOpen(next);
      }}
      trigger={trigger}
      container={container}
      className="edit-sheet"
      actions={
        <>
          <DialogClose render={<Button variant="secondary">{t('edit.change.reject')}</Button>} />
          <Button
            disabled={choice === '' || choice === current}
            onClick={() => {
              onApply(choice);
              setOpen(false);
            }}
          >
            {t('edit.change.apply')}
          </Button>
        </>
      }
    >
      <DialogClose
        render={<CloseButton label={t('edit.sfx.close')} className="absolute top-4 right-4" />}
      />
      <div className="edit-sheet-tiles">
        {items.map((item) => (
          <button
            key={item.value}
            type="button"
            aria-pressed={choice === item.value}
            className="edit-sheet-tile focus-ring"
            onClick={() => setChoice(item.value)}
          >
            <span aria-hidden="true">
              <Image size={24} />
            </span>
            {item.label}
          </button>
        ))}
      </div>
    </Dialog>
  );
}

function SfxPicker({
  open,
  onOpenChange,
  onAdd,
  disabled,
  items,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onAdd: (item: CatalogItem) => void;
  disabled: boolean;
  items: readonly CatalogItem[];
  children: ReactNode;
}) {
  const { t, language } = useLocale();
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={t('edit.sfx.title')}
      description={t('audio.sfx.rule')}
      label={t('edit.sfx.title')}
      actions={<DialogClose render={<Button variant="secondary">{t('edit.sfx.close')}</Button>} />}
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
      {children}
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
 * One dialogue line. The emphasis word is marked inside the line: a press on a
 * word toggles it. The pencil opens the caption text; the spoken text is not
 * asked for, it follows the caption so voice and caption never drift apart.
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
  const [writing, setWriting] = useState(false);
  const points = Array.from(line.display_text);
  const words = wordSpans(line.display_text);

  return (
    <div data-slot="line-editor" className="edit-dialogue">
      <span className="edit-dialogue-number">{index + 1}</span>
      {writing ? (
        <>
          <textarea
            ref={(element) => element?.focus()}
            aria-label={t('edit.scene.displayTextLabel', { number: index + 1 })}
            value={display}
            onChange={(event) => setDisplay(event.target.value)}
            rows={1}
            className="edit-dialogue-input focus-ring"
          />
          <div className="edit-dialogue-buttons">
            <Button
              size="sm"
              variant="secondary"
              onClick={() => {
                setDisplay(line.display_text);
                setWriting(false);
              }}
            >
              {t('edit.change.reject')}
            </Button>
            <Button
              size="sm"
              disabled={display.trim() === '' || display === line.display_text || edit.busy}
              onClick={() => {
                edit.applyLine(sceneId, line.id, display, display);
                setWriting(false);
              }}
            >
              {t('edit.scene.saveLine')}
            </Button>
          </div>
        </>
      ) : (
        <>
          <p className="edit-dialogue-text">
            {words.map((word, position) => {
              const active = spanSelected(line.highlight, word);
              return (
                <span key={word.start}>
                  {points.slice(words[position - 1]?.end ?? 0, word.start).join('')}
                  <button
                    type="button"
                    aria-pressed={active}
                    disabled={edit.busy}
                    className="edit-word hit-area focus-ring"
                    onClick={() =>
                      edit.applyField({
                        kind: 'highlight',
                        lineId: line.id,
                        spans: toggleSpan(line.highlight, word),
                      })
                    }
                  >
                    {word.text}
                  </button>
                </span>
              );
            })}
            {points.slice(words.at(-1)?.end ?? 0).join('')}
          </p>
          <IconButton
            size="compact"
            label={t('edit.scene.editLine', { number: index + 1 })}
            className="edit-dialogue-edit"
            disabled={edit.busy}
            onClick={() => setWriting(true)}
          >
            <Pencil aria-hidden="true" />
          </IconButton>
        </>
      )}
    </div>
  );
}

function SceneForm({ edit, scene, host }: { edit: EditValue; scene: Scene; host: HTMLElement | null }) {
  const { t } = useLocale();
  const [pickerOpen, setPickerOpen] = useState(false);
  const character = scene.visual?.characters[0];
  const background = scene.visual?.background_id ?? '';
  const backgrounds = edit.styleOptions?.backgrounds ?? [];
  const expressions = edit.styleOptions?.expressions ?? [];
  const expression = character?.expression_id ?? expressions[0] ?? '';
  const anchor = character?.anchor ?? 'center';
  const cues = scene.visual?.sfx ?? [];
  const backgroundIds = [...new Set([...(background ? [background] : []), ...backgrounds])];
  const expressionIds = [...new Set([...(expression ? [expression] : []), ...expressions])];
  const backgroundItems = backgroundIds.map((id) => ({
    value: id,
    label: sceneVisualLabel(t, 'background', id, backgrounds),
  }));
  const expressionItems = expressionIds.map((id) => ({
    value: id,
    label: sceneVisualLabel(t, 'expression', id, expressions),
  }));
  const positionItems = POSITION_CHOICES.map((choice) => ({ value: choice.anchor, label: t(choice.labelKey) }));
  const noVisual = scene.visual === null || scene.visual === undefined;

  const apply = (patch: SceneFieldPatch) => edit.applyField(patch);
  const band = edit.band !== null && edit.band.sceneId === scene.id ? edit.band : null;
  const backgroundName = backgroundItems.find((item) => item.value === background)?.label ?? t('edit.change.none');
  const sfxNames = cues.map((cue) => labelFor(t, 'edit.sfx.name', cue.sfx_id.id)).join(', ');

  return (
    <div data-slot="scene-form" className="edit-form">
      <Swept fields={['lines', 'highlight']} band={band} className="edit-group">
        <h3 className="edit-group-title">
          {t('edit.scene.lines')}
          <small data-slot="edit-line-count">
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

      <Swept fields={['expression', 'position']} band={band}>
        <SettingsRow
          className="edit-field-group"
          label={t('edit.scene.characterGroup')}
          control={
            <>
              <ValueField
                className="edit-scene-field"
                label={t('edit.scene.expression')}
                name={t('edit.scene.expression')}
                items={expressionItems}
                value={expression}
                disabled={noVisual || edit.busy}
                onValueChange={(expressionId) => apply({ kind: 'expression', expressionId })}
              />
              <ValueField
                className="edit-scene-field"
                label={t('edit.scene.position')}
                name={t('edit.scene.position')}
                items={positionItems}
                value={anchor}
                disabled={noVisual || edit.busy}
                onValueChange={(next) => apply({ kind: 'position', anchor: next })}
              />
            </>
          }
        />
      </Swept>

      <Swept fields={['background', 'sfx']} band={band}>
        <SettingsRow
          className="edit-field-group"
          label={t('edit.scene.backgroundGroup')}
          control={
            <>
              <BackgroundPicker
                current={background}
                items={backgroundItems}
                container={host}
                onApply={(value) => apply({ kind: 'background', value })}
                trigger={
                  <button
                    type="button"
                    aria-label={t('edit.scene.background')}
                    className="field-trigger field-trigger--named edit-scene-field hit-area focus-ring"
                    disabled={backgroundItems.length === 0 || edit.busy}
                  >
                    {fieldContent(t('edit.scene.background'), backgroundName)}
                  </button>
                }
              />
              <button
                type="button"
                aria-label={t('edit.scene.sfx')}
                aria-haspopup="dialog"
                className="field-trigger field-trigger--named edit-scene-field hit-area focus-ring"
                disabled={noVisual || edit.busy}
                onClick={() => setPickerOpen(true)}
              >
                {fieldContent(t('edit.scene.sfx'), cues.length === 0 ? t('edit.change.none') : sfxNames)}
              </button>
            </>
          }
        />
      </Swept>

      <SfxPicker
        open={pickerOpen}
        onOpenChange={setPickerOpen}
        disabled={cues.length >= 2 || edit.busy}
        items={edit.sfx}
        onAdd={(item) => {
          if (cues.length >= 2) return;
          edit.addSfx(scene.id, item);
          setPickerOpen(false);
        }}
      >
        <ul className="edit-cues">
          {cues.map((cue, index) => {
            const name = labelFor(t, 'edit.sfx.name', cue.sfx_id.id);
            return (
              <li key={`${cue.sfx_id.id}-${index}`}>
                <Music aria-hidden size={16} />
                <span className="truncate">{name}</span>
                <IconButton
                  size="compact"
                  label={t('edit.scene.sfxRemove', { name })}
                  onClick={() => apply({ kind: 'sfx', cues: cues.filter((entry) => entry !== cue) })}
                >
                  <Trash2 aria-hidden size={16} />
                </IconButton>
              </li>
            );
          })}
        </ul>
        <p className="edit-cues-note">{cues.length === 0 ? t('edit.scene.sfxEmpty') : t('edit.scene.sfxLimit')}</p>
      </SfxPicker>
    </div>
  );
}

/**
 * The right panel. The toggle at the end of the heading row picks the scope:
 * values of the picked scene, or values of the whole video. Each value has
 * one place; the sheets for background, voice and BGM open over this column.
 */
export function ScenePanel({ edit }: { edit: EditValue }) {
  const { t } = useLocale();
  const [host, setHost] = useState<HTMLDivElement | null>(null);
  const preview = useAudioPreview();
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

  const whole = edit.tab === 'whole';
  const scene = edit.selectedScene;
  const title = whole
    ? t('edit.tabs.whole')
    : t('edit.scene.number', { number: sceneNumber(edit.video, scene?.id ?? null) });

  return (
    <div
      ref={setHost}
      data-slot="whole-picker-host"
      aria-label={t('edit.scene.form')}
      className="edit-panel-host"
    >
      {edit.actionError === null ? null : (
        <div className="edit-panel-error">
          <Notice tone="error">{t(edit.actionError)}</Notice>
          <CloseButton label={t('edit.error.dismiss')} onClick={edit.dismissError} />
        </div>
      )}
      <Tabs
        items={tabItems}
        label={t('edit.tabs.label')}
        value={edit.tab}
        onValueChange={(value) => {
          preview.stop();
          edit.setTab(value);
        }}
        className="edit-scope-tabs"
        heading={
          <h2 className="edit-scope-title" aria-label={title}>
            {title}
            <small>· {t(whole ? 'edit.settings.scope' : 'edit.scene.scope')}</small>
          </h2>
        }
      >
        <TabsPanel value="whole" className="edit-scope-panel">
          <ScrollPane label={t('edit.tabs.whole')} jumpLabel={t('shell.scroll.jump')} className="min-h-0 flex-1">
            <WholePanel edit={edit} preview={preview} />
          </ScrollPane>
        </TabsPanel>
        <TabsPanel value="scenes" className="edit-scope-panel">
          {scene === null ? (
            <EmptyState title={t('edit.scene.chooseTitle')}>{t('edit.scene.chooseBody')}</EmptyState>
          ) : (
            <ScrollPane label={t('edit.scene.form')} jumpLabel={t('shell.scroll.jump')} className="min-h-0 flex-1">
              <SceneForm key={scene.id} edit={edit} scene={scene} host={host} />
            </ScrollPane>
          )}
        </TabsPanel>
      </Tabs>
    </div>
  );
}
