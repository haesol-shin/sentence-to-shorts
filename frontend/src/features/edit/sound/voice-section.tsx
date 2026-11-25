import { useState } from 'react';
import { Play, Square } from 'lucide-react';

import { Button } from '@/components/Button/Button';
import { IconButton } from '@/components/IconButton/IconButton';
import { Notice } from '@/components/Notice/Notice';
import { SettingsRow } from '@/components/SettingsRow/SettingsRow';
import { Tag } from '@/components/Tag/Tag';
import { useLocale } from '@/shared/lib/i18n/locale';

import type { EditValue } from '../edit-context';
import { readAudio } from './model';
import { VoiceCard } from './value-cards';
import type { AudioPreview } from './use-audio-preview';

/** The voice is only picked here; the real speech is made when the video is made. */
export function VoiceSection({ edit, preview }: { edit: EditValue; preview: AudioPreview }) {
  const { t, language } = useLocale();
  const [open, setOpen] = useState(false);
  const { voiceId } = readAudio(edit.video);
  const current = edit.voices.find((item) => item.id === voiceId);
  const name = current?.label[language] ?? voiceId ?? t('audio.voice.none');
  const key = voiceId === null ? null : `voice:${voiceId}`;
  const sounding = key !== null && preview.playing === key;

  return (
    <section data-slot="voice-section" className="flex flex-col gap-1">
      <h3 className="text-[15px] font-bold text-[var(--text-strong)]">{t('audio.voice.title')}</h3>
      <SettingsRow
        label={t('audio.voice.current')}
        control={
          <>
            <Tag>{name}</Tag>
            <IconButton
              label={t(sounding ? 'audio.preview.stopNamed' : 'audio.preview.listenNamed', { name })}
              data-slot="voice-listen"
              disabled={voiceId === null}
              onClick={() => {
                if (voiceId === null || key === null) return;
                preview.toggle(key, () => edit.audio.previewUrl('voice', voiceId));
              }}
            >
              {sounding ? <Square aria-hidden size={16} fill="currentColor" /> : <Play aria-hidden size={16} fill="currentColor" className="play-glyph" />}
            </IconButton>
            <Button
              variant="ghost"
              data-slot="voice-change"
              disabled={edit.settingsBusy}
              onClick={() => setOpen(true)}
            >
              {t('audio.voice.change')}
            </Button>
          </>
        }
      />
      {preview.problem !== null && preview.problem.key === key && !open ? (
        <Notice tone="warning">
          {t(preview.problem.kind === 'unavailable' ? 'audio.preview.unavailable' : 'audio.preview.failed')}
        </Notice>
      ) : null}
      <p className="text-[13px] text-[var(--text-muted)]">{t('audio.voice.note')}</p>
      <VoiceCard edit={edit} preview={preview} open={open} onOpenChange={setOpen} />
    </section>
  );
}
