import { Sparkles } from 'lucide-react';

import { Button } from '@/components/Button/Button';
import { RadioGroup } from '@/components/RadioGroup/RadioGroup';
import { ScrollPane } from '@/components/ScrollPane/ScrollPane';
import { SettingsRow } from '@/components/SettingsRow/SettingsRow';
import { ValueField } from '@/components/ValueField/ValueField';
import { useLocale } from '@/shared/lib/i18n/locale';

import type { EditValue } from '../edit-context';
import {
  CAPTION_FONT_PATH,
  CAPTION_MODES,
  CAPTION_POSITION_PATH,
  CAPTION_POSITIONS,
  modeChanges,
  readCaption,
} from './model';

/** The default caption values of the whole video: mode, font and position. */
export function CaptionsTab({ edit }: { edit: EditValue }) {
  const { t, language } = useLocale();
  const caption = readCaption(edit.video);
  const options = edit.captionOptions;
  const disabled = edit.video === null || edit.settingsBusy;
  const undoDisabled = disabled || !edit.canUndo;

  const unavailableModes = CAPTION_MODES.filter((mode) => !options?.modes.includes(mode));
  const fontItems = edit.fonts.map((font) => ({
    value: font.id,
    label: font.label[language],
    disabled: options?.fonts.includes(font.id) !== true,
  }));
  if (caption.fontId !== null && !fontItems.some((item) => item.value === caption.fontId)) {
    fontItems.unshift({ value: caption.fontId, label: caption.fontId, disabled: true });
  }
  const positionItems = CAPTION_POSITIONS.map((position) => ({
    value: position,
    label: t(`audio.caption.position.${position}`),
  }));

  return (
    <ScrollPane label={t('audio.caption.label')} className="min-h-0 flex-1">
      <div data-slot="captions-tab" className="flex flex-col gap-5 pb-16">
        <div className="flex justify-end">
          <Button
            variant="ghost"
            disabled={undoDisabled}
            onClick={() => {
              if (!undoDisabled) edit.undo();
            }}
            iconStart={<Sparkles aria-hidden size={16} />}
          >
            {t('edit.scene.undo')}
          </Button>
        </div>
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

        <section data-slot="caption-font" className="flex flex-col gap-1">
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
        </section>

        <section data-slot="caption-position" className="flex flex-col gap-1">
          <SettingsRow
            label={t('audio.caption.position')}
            description={t('audio.caption.positionHelp')}
            control={
              <ValueField
                label={t('audio.caption.position')}
                items={positionItems}
                value={caption.position}
                disabled={disabled}
                onValueChange={(value) => {
                  if (!disabled && value !== caption.position) {
                    edit.applySettings([{ path: CAPTION_POSITION_PATH, value }]);
                  }
                }}
              />
            }
          />
        </section>
      </div>
    </ScrollPane>
  );
}
