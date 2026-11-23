import { useEffect, useMemo, useRef, useState } from 'react';

import { RadioGroup } from '@/components/RadioGroup/RadioGroup';
import { ScrollPane } from '@/components/ScrollPane/ScrollPane';
import { SettingsRow } from '@/components/SettingsRow/SettingsRow';
import { ValueField } from '@/components/ValueField/ValueField';
import { useLocale } from '@/shared/lib/i18n/locale';

import type { CatalogItem, ErrorItem } from '../api';
import type { EditValue } from '../edit-context';
import { CaptionIssues, type ShownIssue } from './caption-issues';
import { ExtraLayer } from './extra-layer';
import {
  CAPTION_EXTRA_PATH,
  CAPTION_FONT_PATH,
  CAPTION_MODES,
  CAPTION_POSITION_PATH,
  CAPTION_POSITIONS,
  changeLanguage,
  extraChanges,
  fontChoices,
  issuesFromErrors,
  missingLines,
  modeChanges,
  pairFits,
  readCaption,
  savedDraft,
  sameDraft,
  startDraft,
  type CaptionPosition,
  type ExtraDraft,
} from './model';
import { PositionField } from './position-field';
import { useCaptionLayout } from './use-caption-layout';

const NO_POSITIONS: ReadonlySet<CaptionPosition> = new Set();

/** The caption values of the whole video: mode, the first layer's font and position, and the second layer. */
export function CaptionsTab({ edit }: { edit: EditValue }) {
  const { t, language } = useLocale();
  const caption = readCaption(edit.video);
  const options = edit.captionOptions;
  const disabled = edit.video === null || edit.settingsBusy;
  const videoId = edit.video?.id ?? null;
  const layoutId = edit.video?.settings.format.layout?.id ?? null;

  const saved = useMemo(() => savedDraft(edit.video), [edit.video]);
  const savedKey = JSON.stringify(saved);
  const [syncedKey, setSyncedKey] = useState(savedKey);
  const [draft, setDraft] = useState<ExtraDraft | null>(saved);
  const [attempted, setAttempted] = useState(false);
  const [hiddenErrors, setHiddenErrors] = useState<readonly ErrorItem[] | null>(null);
  if (syncedKey !== savedKey) {
    setSyncedKey(savedKey);
    setDraft(saved);
    setAttempted(false);
  }

  const source = useRef(edit.caption);
  source.current = edit.caption;
  const [languages, setLanguages] = useState<readonly CatalogItem[] | null>(null);
  const [languagesFailed, setLanguagesFailed] = useState(false);
  const [singleLayer, setSingleLayer] = useState(false);
  useEffect(() => {
    if (videoId === null) return;
    let current = true;
    source.current
      .languages()
      .then((items) => {
        if (!current) return;
        setLanguages(items);
        setLanguagesFailed(false);
      })
      .catch(() => {
        if (current) setLanguagesFailed(true);
      });
    return () => {
      current = false;
    };
  }, [videoId]);
  useEffect(() => {
    if (videoId === null) return;
    let current = true;
    source.current
      .singleLayer()
      .then((single) => {
        if (current) setSingleLayer(single);
      })
      .catch(() => {
        if (current) setSingleLayer(false);
      });
    return () => {
      current = false;
    };
  }, [videoId, layoutId]);

  const draftFont = edit.fonts.find((font) => font.id === draft?.fontId);
  const { layout, failed } = useCaptionLayout(
    edit.caption,
    {
      extraLanguage: draft?.language ?? null,
      extraFont: draftFont === undefined ? null : { id: draftFont.id, revision: draftFont.revision },
    },
    edit.video?.revision ?? null,
  );

  const positionLabel = (position: CaptionPosition) => t(`audio.caption.position.${position}`);
  const blockedList = (blocked: ReadonlySet<CaptionPosition>) =>
    CAPTION_POSITIONS.filter((position) => blocked.has(position)).map(positionLabel).join(', ');
  const primaryBlocked =
    layout === null
      ? NO_POSITIONS
      : new Set(
          CAPTION_POSITIONS.filter(
            (position) => pairFits(layout, position, draft?.position ?? position) === false,
          ),
        );
  const extraBlocked =
    layout === null || draft === null
      ? NO_POSITIONS
      : new Set(CAPTION_POSITIONS.filter((position) => pairFits(layout, caption.position, position) === false));

  const fontItems = fontChoices(edit.fonts, options?.fonts ?? null, caption.fontId, language);
  const unavailableModes = CAPTION_MODES.filter((mode) => !options?.modes.includes(mode));

  const edited = (next: ExtraDraft | null) => {
    setDraft(next);
    setHiddenErrors(edit.changeErrors);
  };

  const selectLanguage = (value: string | null) => {
    if (value === null) {
      if (saved !== null) edit.applySettings([{ path: CAPTION_EXTRA_PATH, value: [] }]);
      edited(null);
      return;
    }
    edited(draft === null ? startDraft(edit.video, value) : changeLanguage(edit.video, draft, value));
  };

  const apply = () => {
    if (draft === null || edit.video === null || disabled) return;
    if (missingLines(edit.video, draft).length > 0) {
      setAttempted(true);
      return;
    }
    const changes = extraChanges(edit.video, draft, edit.fonts);
    if (changes !== null) edit.applySettings(changes);
  };

  const shown: ShownIssue[] = edit.changeErrors === hiddenErrors
    ? []
    : issuesFromErrors(edit.changeErrors, edit.video).map((issue) => ({ ...issue, tone: 'error' as const }));
  if (draft !== null && (attempted || saved !== null)) {
    const lines = missingLines(edit.video, draft);
    if (lines.length > 0 && !shown.some((issue) => issue.code === 'caption_text_missing')) {
      shown.push({ code: 'caption_text_missing', layer: 'extra', lines, tone: 'error' });
    }
  }
  if (
    draft !== null &&
    pairFits(layout, caption.position, draft.position) === false &&
    !shown.some((issue) => issue.code === 'caption_overlap')
  ) {
    shown.push({ code: 'caption_overlap', layer: 'both', lines: [], tone: 'warning', kept: true });
  }

  const primaryNote = primaryBlocked.size === 0
    ? undefined
    : draft === null
      ? t('audio.caption.positionBlockedSingle', { list: blockedList(primaryBlocked) })
      : t('audio.caption.positionBlocked', {
          layer: t('audio.caption.layer.extra'),
          other: positionLabel(draft.position),
          list: blockedList(primaryBlocked),
        });
  const extraNote = extraBlocked.size === 0
    ? undefined
    : t('audio.caption.positionBlocked', {
        layer: t('audio.caption.layer.primary'),
        other: positionLabel(caption.position),
        list: blockedList(extraBlocked),
      });
  const sizeNote = layout === null
    ? undefined
    : layout.extra_px === null
      ? t('audio.caption.sizeSingle', { primary: layout.primary_px })
      : t('audio.caption.size', { primary: layout.primary_px, extra: layout.extra_px });

  return (
    <ScrollPane label={t('audio.caption.label')} jumpLabel={t('shell.scroll.jump')} className="min-h-0 flex-1">
      <div data-slot="captions-tab" className="flex flex-col gap-5 pb-16">
        <CaptionIssues issues={shown} />
        <section data-slot="caption-mode" className="flex flex-col gap-2">
          <h3 className="text-[15px] font-bold text-[var(--text-strong)]">{t('audio.caption.mode')}</h3>
          <RadioGroup
            label={t('audio.caption.mode')}
            value={caption.mode}
            options={CAPTION_MODES.map((mode) => ({
              value: mode,
              label: t(`audio.caption.mode.${mode}`),
              disabled: disabled || unavailableModes.includes(mode),
            }))}
            onValueChange={(value) => {
              const mode = CAPTION_MODES.find((item) => item === value);
              if (disabled || mode === undefined || mode === caption.mode || unavailableModes.includes(mode)) return;
              edit.applySettings(modeChanges(edit.video, mode));
            }}
          />
          <p className="text-[13px] text-[var(--text-muted)]">
            {t(`audio.caption.modeHelp.${caption.mode}`)}
          </p>
          {unavailableModes.length > 0 && (
            <p className="text-[13px] text-[var(--text-muted)]">
              {t(options === null ? 'audio.caption.optionsUnavailable' : 'audio.caption.modeUnavailable')}
            </p>
          )}
        </section>

        <section data-slot="caption-primary" className="flex flex-col gap-2">
          <h3 className="text-[15px] font-bold text-[var(--text-strong)]">{t('audio.caption.primaryTitle')}</h3>
          <div data-slot="caption-font" className="flex flex-col gap-1">
            <SettingsRow
              label={t('audio.caption.font')}
              note={
                options !== null && (fontItems.length === 0 || fontItems.some((item) => item.disabled))
                  ? t('audio.caption.fontUnavailable')
                  : undefined
              }
              control={
                <ValueField
                  label={t('audio.caption.font')}
                  items={fontItems}
                  value={caption.fontId ?? undefined}
                  placeholder={t('audio.caption.fontNone')}
                  disabled={disabled || options === null || fontItems.length === 0}
                  onValueChange={(value) => {
                    if (disabled || value === caption.fontId || !options?.fonts.includes(value)) return;
                    const font = edit.fonts.find((item) => item.id === value);
                    if (font === undefined) return;
                    edit.applySettings([
                      { path: CAPTION_FONT_PATH, value: { id: font.id, revision: font.revision } },
                    ]);
                  }}
                />
              }
            />
          </div>
          <div data-slot="caption-position" className="flex flex-col gap-1">
            <PositionField
              label={t('audio.caption.position')}
              description={t('audio.caption.positionHelp')}
              value={caption.position}
              blocked={primaryBlocked}
              disabled={disabled}
              note={primaryNote}
              onPick={(position) => edit.applySettings([{ path: CAPTION_POSITION_PATH, value: position }])}
            />
          </div>
          {sizeNote !== undefined && (
            <p data-slot="caption-size" className="text-[13px] text-[var(--text-muted)]">
              {sizeNote}
            </p>
          )}
          {failed && (
            <p data-slot="caption-layout-failed" className="text-[13px] text-[var(--text-muted)]">
              {t('audio.caption.layoutUnavailable')}
            </p>
          )}
        </section>

        <ExtraLayer
          edit={edit}
          draft={draft}
          dirty={!sameDraft(draft, saved)}
          disabled={disabled}
          languages={languages}
          languagesFailed={languagesFailed}
          singleLayer={singleLayer}
          blocked={extraBlocked}
          positionNote={extraNote}
          showMissing={attempted || saved !== null}
          onChange={edited}
          onLanguage={selectLanguage}
          onApply={apply}
        />
      </div>
    </ScrollPane>
  );
}
