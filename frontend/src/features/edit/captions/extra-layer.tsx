import { Button } from '@/components/Button/Button';
import { SettingsRow } from '@/components/SettingsRow/SettingsRow';
import { Tag } from '@/components/Tag/Tag';
import { TextField } from '@/components/TextField/TextField';
import { ValueField } from '@/components/ValueField/ValueField';
import { useLocale } from '@/shared/lib/i18n/locale';

import type { CatalogItem } from '../api';
import type { EditValue } from '../edit-context';
import { PositionField } from './position-field';
import {
  fontChoices,
  lineRefs,
  missingLines,
  type CaptionPosition,
  type ExtraDraft,
} from './model';

const NONE = 'none';

/**
 * The second caption layer: its language from the catalog, font, position and
 * one translation per line. The values are saved together by the apply button;
 * turning the layer off saves at once.
 */
export function ExtraLayer({
  edit,
  draft,
  dirty,
  disabled,
  languages,
  languagesFailed,
  singleLayer,
  blocked,
  positionNote,
  showMissing,
  onChange,
  onLanguage,
  onApply,
}: {
  edit: EditValue;
  draft: ExtraDraft | null;
  dirty: boolean;
  disabled: boolean;
  /** The catalog languages; null until the list has loaded. */
  languages: readonly CatalogItem[] | null;
  languagesFailed: boolean;
  singleLayer: boolean;
  blocked: ReadonlySet<CaptionPosition>;
  positionNote: string | undefined;
  showMissing: boolean;
  onChange: (next: ExtraDraft) => void;
  onLanguage: (language: string | null) => void;
  onApply: () => void;
}) {
  const { t, language } = useLocale();
  const options = edit.captionOptions;
  const languageItems = [
    { value: NONE, label: t('audio.caption.extra.languageNone') },
    ...(languages ?? []).map((item) => ({ value: item.id, label: item.label[language] })),
  ];
  const fontItems = fontChoices(edit.fonts, options?.fonts ?? null, draft?.fontId ?? null, language);
  const missing = draft === null ? [] : missingLines(edit.video, draft);
  const missingIds = new Set(missing.map((line) => line.lineId));

  return (
    <section data-slot="caption-extra" className="flex flex-col gap-2">
      <h3 className="text-[15px] font-bold text-[var(--text-strong)]">{t('audio.caption.extra.title')}</h3>
      <p className="text-[13px] text-[var(--text-muted)]">{t('audio.caption.extra.help')}</p>
      {singleLayer && (
        <p data-slot="caption-single-layer" className="text-[13px] text-[var(--text-muted)]">
          {t('audio.caption.extra.singleLayer')}
        </p>
      )}
      <SettingsRow
        label={t('audio.caption.extra.language')}
        note={languagesFailed ? t('audio.caption.extra.languagesUnavailable') : undefined}
        control={
          <ValueField
            label={t('audio.caption.extra.language')}
            items={languageItems}
            value={draft?.language ?? NONE}
            disabled={disabled || languages === null}
            onValueChange={(value) => {
              if (disabled || value === (draft?.language ?? NONE)) return;
              onLanguage(value === NONE ? null : value);
            }}
          />
        }
      />
      {draft !== null && (
        <>
          <SettingsRow
            label={t('audio.caption.extra.font')}
            note={
              options !== null && fontItems.some((item) => item.disabled)
                ? t('audio.caption.fontUnavailable')
                : undefined
            }
            control={
              <ValueField
                label={t('audio.caption.extra.font')}
                items={fontItems}
                value={draft.fontId ?? undefined}
                placeholder={t('audio.caption.fontNone')}
                disabled={disabled || options === null || fontItems.length === 0}
                onValueChange={(value) => {
                  if (disabled || value === draft.fontId || options?.fonts.includes(value) !== true) return;
                  onChange({ ...draft, fontId: value });
                }}
              />
            }
          />
          <PositionField
            label={t('audio.caption.extra.position')}
            value={draft.position}
            blocked={blocked}
            disabled={disabled}
            note={positionNote}
            onPick={(position) => onChange({ ...draft, position })}
          />
          <SettingsRow
            label={t('audio.caption.extra.modeLabel')}
            description={t('audio.caption.extra.modeHelp')}
            control={<Tag>{t(`audio.caption.mode.${draft.mode}`)}</Tag>}
          />
          <h4 className="text-[14px] font-bold text-[var(--text-strong)]">{t('audio.caption.translations')}</h4>
          <div data-slot="caption-translations" className="flex flex-col gap-3">
            {lineRefs(edit.video).map((line) => (
              <div key={line.lineId} className="flex flex-col gap-1">
                <p className="text-[13px] text-[var(--text-muted)]">{line.text}</p>
                <TextField
                  label={t('audio.caption.lineTranslation', { scene: line.sceneNumber, line: line.lineNumber })}
                  value={draft.texts[line.lineId] ?? ''}
                  disabled={disabled}
                  error={showMissing && missingIds.has(line.lineId) ? t('audio.caption.translationMissing') : undefined}
                  onChange={(event) =>
                    onChange({ ...draft, texts: { ...draft.texts, [line.lineId]: event.target.value } })
                  }
                />
              </div>
            ))}
          </div>
          {dirty && <p className="text-[13px] text-[var(--text-muted)]">{t('audio.caption.extra.unsaved')}</p>}
          <div className="flex justify-end">
            <Button variant="primary" disabled={disabled || !dirty || draft.fontId === null} onClick={onApply}>
              {t('audio.caption.apply')}
            </Button>
          </div>
        </>
      )}
    </section>
  );
}
