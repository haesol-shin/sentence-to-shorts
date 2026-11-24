import { useEffect, useRef, useState, type ReactNode } from 'react';

import { Notice } from '@/components/Notice/Notice';
import { SettingsRow } from '@/components/SettingsRow/SettingsRow';
import { TopBarItem } from '@/components/TopBarItem/TopBarItem';
import { readCaption } from '@/features/edit/captions/model';
import { useEditOptional } from '@/features/edit/edit-context';
import { readAudio } from '@/features/edit/sound/model';
import { useAudioPreview } from '@/features/edit/sound/use-audio-preview';
import { BgmCard, VoiceCard } from '@/features/edit/sound/value-cards';
import { useLocale } from '@/shared/lib/i18n/locale';
import { cn } from '@/shared/lib/utils';

type Card = 'voice' | 'bgm';

/** The caption mode is named as the result screen names it. */
const CAPTION_MODE_KEYS = {
  sentence: 'export.fact.captionSentence',
  phrase: 'export.fact.captionPhrase',
  typewriter: 'export.fact.captionTypewriter',
} as const;

/** The value of a row that opens a card fills the row beside the label, so the value is the control. */
const VALUE_BUTTON =
  'focus-ring flex min-w-0 flex-1 cursor-pointer items-center self-stretch rounded-[var(--radius-inset)] text-left disabled:cursor-not-allowed disabled:text-[var(--disabled-foreground)]';

function GroupTitle({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <h3
      className={cn(
        'text-[length:var(--font-size-small)] leading-[18px] font-bold text-[var(--muted-foreground)]',
        className,
      )}
    >
      {children}
    </h3>
  );
}

function Value({ children }: { children: ReactNode }) {
  return <span className="min-w-0 flex-1 truncate">{children}</span>;
}

/**
 * The video-wide values open under the top bar item. The panel keeps its right
 * edge on the button's right edge at every desktop width, and the stage behind
 * it lightens until the reader presses outside or Escape. Voice and BGM open
 * their own card over the panel; while a card is open, outside presses and
 * Escape belong to the card and the panel stays.
 */
export function VideoSettings() {
  const { t, language } = useLocale();
  const edit = useEditOptional();
  const preview = useAudioPreview();
  const [open, setOpen] = useState(false);
  const [card, setCard] = useState<Card | null>(null);
  const wrapper = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const [panel, setPanel] = useState<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open || card !== null) return undefined;
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
  }, [open, card]);

  useEffect(() => {
    if (!open) preview.stop();
  }, [open, preview]);

  const video = edit?.video ?? null;
  const { voiceId, bgm } = readAudio(video);
  const caption = readCaption(video);
  const languageLabel =
    video === null
      ? null
      : video.settings.language === 'ko'
        ? t('edit.settings.languageKo')
        : t('edit.settings.languageEn');
  const duration =
    video === null ? null : t('edit.settings.durationValue', { seconds: video.settings.target_duration_s });
  const voice =
    edit === null || video === null
      ? null
      : edit.voices.find((item) => item.id === voiceId)?.label[language] ?? voiceId ?? t('audio.voice.none');
  const track = edit?.bgm.find((item) => item.id === bgm.entryId);
  const bgmValue = !bgm.enabled
    ? t('edit.settings.off')
    : track?.label[language] ?? bgm.entryId ?? t('audio.bgm.trackNone');
  const bgmReady = edit !== null && edit.bgmStatus === 'ready';
  const font =
    caption.fontId === null
      ? t('audio.caption.fontNone')
      : edit?.fonts.find((item) => item.id === caption.fontId)?.label[language] ?? caption.fontId;

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
            className="fixed top-[var(--layout-topbar-h)] right-0 bottom-0 left-[var(--layout-sidebar-w-sm)] z-[var(--z-panel)] bg-[var(--overlay-scrim)] md:left-[var(--layout-sidebar-w)]"
            onClick={() => setOpen(false)}
          />
          <div
            ref={setPanel}
            id="video-settings-panel"
            role="dialog"
            aria-label={t('edit.settings.title')}
            data-slot="video-settings-panel"
            className="absolute top-[calc(100%+var(--space-12))] right-0 z-[calc(var(--z-panel)+1)] flex w-95 max-w-[calc(100vw-var(--space-48))] flex-col gap-2 rounded-[var(--radius-surface)] border border-[var(--border)] bg-[var(--popover)] p-5 shadow-[var(--shadow-float)]"
          >
            <h2 className="text-[length:var(--font-size-body)] leading-5 font-bold text-[var(--text-strong)]">
              {t('edit.settings.title')}
            </h2>
            <p className="-mt-0.5 text-[length:var(--font-size-small)] leading-[18px] text-[var(--muted-foreground)]">
              {t('edit.settings.scope')}
            </p>
            {edit === null || video === null ? (
              <Notice>{t('edit.settings.loading')}</Notice>
            ) : (
              <>
                <GroupTitle className="mt-1">{t('edit.settings.groupVideo')}</GroupTitle>
                <SettingsRow
                  className="settings-row--field"
                  label={t('edit.settings.language')}
                  control={<Value>{languageLabel}</Value>}
                />
                <SettingsRow
                  className="settings-row--field"
                  label={t('edit.settings.duration')}
                  control={<Value>{duration}</Value>}
                />
                <GroupTitle>{t('edit.settings.groupSound')}</GroupTitle>
                <SettingsRow
                  className="settings-row--field"
                  label={t('edit.settings.voice')}
                  control={
                    <button
                      type="button"
                      className={VALUE_BUTTON}
                      data-slot="settings-voice"
                      aria-haspopup="dialog"
                      disabled={edit.settingsBusy}
                      onClick={() => setCard('voice')}
                    >
                      <span className="min-w-0 truncate">{voice}</span>
                    </button>
                  }
                />
                <SettingsRow
                  className="settings-row--field"
                  label={t('edit.settings.bgm')}
                  control={
                    <button
                      type="button"
                      className={VALUE_BUTTON}
                      data-slot="settings-bgm"
                      aria-haspopup="dialog"
                      disabled={!bgm.enabled || !bgmReady || edit.settingsBusy}
                      onClick={() => setCard('bgm')}
                    >
                      <span className="min-w-0 truncate">{bgmValue}</span>
                    </button>
                  }
                />
                <GroupTitle>{t('edit.settings.groupCaption')}</GroupTitle>
                <SettingsRow
                  className="settings-row--field"
                  label={t('audio.caption.mode')}
                  control={<Value>{t(CAPTION_MODE_KEYS[caption.mode])}</Value>}
                />
                <SettingsRow
                  className="settings-row--field"
                  label={t('audio.caption.font')}
                  control={<Value>{font}</Value>}
                />
                <VoiceCard
                  edit={edit}
                  preview={preview}
                  open={card === 'voice'}
                  onOpenChange={(next) => setCard(next ? 'voice' : null)}
                  container={panel}
                />
                <BgmCard
                  edit={edit}
                  preview={preview}
                  open={card === 'bgm'}
                  onOpenChange={(next) => setCard(next ? 'bgm' : null)}
                  container={panel}
                />
              </>
            )}
          </div>
        </>
      ) : null}
    </div>
  );
}
