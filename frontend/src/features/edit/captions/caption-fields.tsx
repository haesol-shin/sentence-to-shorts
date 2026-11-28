import { Button } from '@/components/Button/Button';
import { CloseButton } from '@/components/CloseButton/CloseButton';
import { Dialog, DialogClose } from '@/components/Dialog/Dialog';
import { RadioGroup } from '@/components/RadioGroup/RadioGroup';
import { ValueField } from '@/components/ValueField/ValueField';
import { useLocale } from '@/shared/lib/i18n/locale';

import type { EditValue } from '../edit-context';
import {
  CAPTION_FONT_PATH,
  CAPTION_MODES,
  CAPTION_POSITION_PATH,
  CAPTION_POSITIONS,
  fontChoices,
  modeChanges,
  readCaption,
  type CaptionPosition,
} from './model';
import { PositionField } from './position-field';
import { useCaptionLayout } from './use-caption-layout';

const CAPTION_MODE_KEYS = {
  sentence: 'export.fact.captionSentence',
  phrase: 'export.fact.captionPhrase',
  typewriter: 'export.fact.captionTypewriter',
} as const;

/** Whole-video caption controls. Only the primary caption can be edited. */
export function CaptionFields({ edit, container }: { edit: EditValue; container?: HTMLElement }) {
  const { t, language } = useLocale();
  const caption = readCaption(edit.video);
  const options = edit.captionOptions;
  const disabled = edit.video === null || edit.settingsBusy;
  // Read before the details open so the layout note is ready at first paint when possible.
  const { layout, failed } = useCaptionLayout(edit.caption, edit.video?.revision ?? null);
  const blocked = new Set<CaptionPosition>(
    layout === null || layout.extra_px !== null
      ? []
      : CAPTION_POSITIONS.filter((position) =>
          layout.pairs.some((pair) => pair.primary === position && !pair.fits)),
  );
  const blockedNames = [...blocked].map((position) => t(`audio.caption.position.${position}`));
  const items = fontChoices(edit.fonts, options?.fonts ?? null, caption.fontId, language).map((item) =>
    item.disabled ? { value: item.value, label: item.label, unavailable: true as const, unavailableName: item.label } : item,
  );
  const modeLabel = t('audio.caption.mode');
  const fontLabel = t('audio.caption.font');

  return (
    <section className="whole-panel__group">
      <h3>{t('edit.settings.groupCaption')}</h3>
      <div className="whole-panel__fields">
        <Dialog
          title={modeLabel}
          className="whole-details-sheet"
          container={container}
          trigger={
            <button type="button" className="whole-field whole-field__trigger focus-ring" aria-label={`${modeLabel} ${t(CAPTION_MODE_KEYS[caption.mode])}`} disabled={edit.video === null}>
              <span className="whole-field__name">{modeLabel}</span>
              <span className="whole-field__value">{t(CAPTION_MODE_KEYS[caption.mode])}</span>
            </button>
          }
          actions={<DialogClose render={<Button variant="secondary">{t('audio.picker.close')}</Button>} />}
        >
          <DialogClose
            render={<CloseButton label={t('audio.picker.close')} className="whole-details-sheet__close" />}
          />
          <div className="flex flex-col gap-3">
            <RadioGroup
              label={modeLabel}
              value={caption.mode}
              options={CAPTION_MODES.map((mode) => ({
                value: mode,
                label: t(`audio.caption.mode.${mode}`),
                disabled: disabled || options?.modes.includes(mode) !== true,
              }))}
              onValueChange={(value) => {
                const mode = CAPTION_MODES.find((item) => item === value);
                if (disabled || mode === undefined || mode === caption.mode || !options?.modes.includes(mode)) return;
                edit.applySettings(modeChanges(edit.video, mode));
              }}
            />
            <p>{t(`audio.caption.modeHelp.${caption.mode}`)}</p>
            {options === null || CAPTION_MODES.some((mode) => !options.modes.includes(mode)) ? (
              <p>{t(options === null ? 'audio.caption.optionsUnavailable' : 'audio.caption.modeUnavailable')}</p>
            ) : null}
            <PositionField
              label={t('audio.caption.position')}
              description={t('audio.caption.positionHelp')}
              value={caption.position}
              blocked={blocked}
              disabled={disabled}
              note={blocked.size === 0 ? undefined : t('audio.caption.positionBlockedSingle', { list: blockedNames.join(', ') })}
              onPick={(position) => edit.applySettings([{ path: CAPTION_POSITION_PATH, value: position }])}
            />
            <p className="min-h-[var(--line-height-small)]" data-slot="caption-size">
              {layout !== null
                ? t('audio.caption.sizeSingle', { primary: layout.primary_px })
                : failed ? t('audio.caption.layoutUnavailable') : null}
            </p>
          </div>
        </Dialog>
        <ValueField
          className="whole-panel__select"
          label={fontLabel}
          name={fontLabel}
          items={items}
          value={caption.fontId ?? undefined}
          placeholder={t('audio.caption.fontNone')}
          note={t('audio.caption.fontUnavailable')}
          disabled={disabled || options === null || items.length === 0}
          onValueChange={(value) => {
            if (disabled || value === caption.fontId || !options?.fonts.includes(value)) return;
            const font = edit.fonts.find((item) => item.id === value);
            if (font === undefined) return;
            edit.applySettings([{ path: CAPTION_FONT_PATH, value: { id: font.id, revision: font.revision } }]);
          }}
        />
      </div>
    </section>
  );
}
