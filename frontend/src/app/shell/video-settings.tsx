import { useEffect, useRef, useState } from 'react';

import { Notice } from '@/components/Notice/Notice';
import { SettingsRow } from '@/components/SettingsRow/SettingsRow';
import { Tag } from '@/components/Tag/Tag';
import { TopBarItem } from '@/components/TopBarItem/TopBarItem';
import { useEditOptional } from '@/features/edit/edit-context';
import { useLocale } from '@/shared/lib/i18n/locale';

/**
 * The video-wide values open under the top bar item. The panel keeps its right
 * edge on the button's right edge at every desktop width, and the stage behind
 * it dims until the reader presses outside or Escape.
 */
export function VideoSettings() {
  const { t, language } = useLocale();
  const edit = useEditOptional();
  const [open, setOpen] = useState(false);
  const wrapper = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return undefined;
    const onPointerDown = (event: PointerEvent) => {
      if (wrapper.current !== null && !wrapper.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      setOpen(false);
      trigger.current?.focus();
    };
    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open]);

  const video = edit?.video ?? null;
  const languageLabel =
    video === null
      ? null
      : video.settings.language === 'ko'
        ? t('edit.settings.languageKo')
        : t('edit.settings.languageEn');
  const duration =
    video === null ? null : t('edit.settings.durationValue', { seconds: video.settings.target_duration_s });
  const voice =
    video === null
      ? null
      : edit?.voices.find((item) => item.id === video.settings.audio.voice.id)?.label[language] ??
        video.settings.audio.voice.id;
  const bgm =
    video === null ? null : video.settings.audio.bgm.enabled ? t('edit.settings.on') : t('edit.settings.off');

  return (
    <div ref={wrapper} className="relative inline-flex shrink-0">
      <TopBarItem
        ref={trigger}
        label={t('edit.settings.title')}
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-controls="video-settings-panel"
        data-slot="video-settings"
        onClick={() => setOpen((current) => !current)}
      />
      {open ? (
        <>
          <div
            data-slot="settings-scrim"
            aria-hidden="true"
            className="fixed top-[var(--layout-topbar-h)] right-0 bottom-0 left-[var(--layout-sidebar-w-sm)] z-[var(--z-panel)] bg-[var(--overlay-dialog-scrim)] md:left-[var(--layout-sidebar-w)]"
            onClick={() => setOpen(false)}
          />
          <div
            id="video-settings-panel"
            role="dialog"
            aria-label={t('edit.settings.title')}
            data-slot="video-settings-panel"
            className="absolute top-[calc(100%+4px)] right-0 z-[calc(var(--z-panel)+1)] flex w-80 max-w-[calc(100vw-var(--space-48))] flex-col gap-3 rounded-[var(--radius-surface)] bg-[var(--popover)] p-5 shadow-[var(--shadow-float)]"
          >
            <h2 className="text-[22px] leading-8 font-bold text-[var(--text-strong)]">
              {t('edit.settings.title')}
            </h2>
            {video === null ? (
              <Notice>{t('edit.settings.loading')}</Notice>
            ) : (
              <>
                <SettingsRow
                  label={t('edit.settings.language')}
                  control={<Tag>{languageLabel}</Tag>}
                />
                <SettingsRow
                  label={t('edit.settings.duration')}
                  control={<Tag>{duration}</Tag>}
                />
                <SettingsRow
                  label={t('edit.settings.voice')}
                  control={<Tag>{voice}</Tag>}
                />
                <SettingsRow
                  label={t('edit.settings.bgm')}
                  control={<Tag>{bgm}</Tag>}
                />
              </>
            )}
          </div>
        </>
      ) : null}
    </div>
  );
}
