import { useState } from 'react';
import { Play, Square } from 'lucide-react';

import { IconButton } from '@/components/IconButton/IconButton';
import { Notice } from '@/components/Notice/Notice';
import { useLocale } from '@/shared/lib/i18n/locale';

import { CaptionFields } from './captions/caption-fields';
import type { EditValue } from './edit-context';
import { readAudio } from './sound/model';
import type { AudioPreview } from './sound/use-audio-preview';
import { BgmCard, VoiceCard } from './sound/value-cards';
import './whole-panel.css';

interface WholePanelProps {
  edit: EditValue;
  preview: AudioPreview;
}

/** The values shared by all scenes, under the edit panel's whole-video scope. */
export function WholePanel({ edit, preview }: WholePanelProps) {
  const { t, language } = useLocale();
  const [panel, setPanel] = useState<HTMLDivElement | null>(null);
  const [card, setCard] = useState<'voice' | 'bgm' | null>(null);
  const container = panel?.closest<HTMLElement>('[data-slot="whole-picker-host"]') ?? undefined;
  const { voiceId, bgm } = readAudio(edit.video);
  const voice = edit.voices.find((item) => item.id === voiceId)?.label[language] ?? voiceId ?? t('audio.voice.none');
  const track = edit.bgm.find((item) => item.id === bgm.entryId)?.label[language] ?? bgm.entryId ?? t('audio.bgm.trackNone');
  const voiceKey = voiceId === null ? null : `voice:${voiceId}`;
  const bgmKey = !bgm.enabled || bgm.entryId === null ? null : `bgm:${bgm.entryId}`;
  const problem = card === null && (preview.problem?.key === voiceKey || preview.problem?.key === bgmKey)
    ? preview.problem
    : null;
  const disabled = edit.video === null || edit.settingsBusy;

  return (
    <div ref={setPanel} className="whole-panel" data-slot="whole-panel">
      <section className="whole-panel__group">
        <h3>{t('edit.settings.groupVideo')}</h3>
        <div className="whole-panel__fields">
          <div className="whole-field">
            <span className="whole-field__name">{t('edit.settings.ratio')}</span>
            <span className="whole-field__value">{t('edit.settings.ratioVertical')}</span>
          </div>
        </div>
      </section>

      <section className="whole-panel__group">
        <h3>{t('edit.settings.groupSound')}</h3>
        <div className="whole-panel__fields">
          <div className="whole-field whole-field--audio" data-slot="voice-section">
            <VoiceCard
              edit={edit}
              preview={preview}
              container={container}
              open={card === 'voice'}
              onOpenChange={(open) => setCard(open ? 'voice' : null)}
              trigger={
                <button type="button" className="whole-field__trigger focus-ring" data-slot="voice-change" aria-label={`${t('audio.voice.title')} ${voice}`} disabled={disabled}>
                  <span className="whole-field__name">{t('audio.voice.title')}</span>
                  <span className="whole-field__value">{voice}</span>
                </button>
              }
            />
            <ListenButton
              name={voice}
              playing={voiceKey !== null && preview.playing === voiceKey}
              disabled={voiceId === null}
              slot="voice-listen"
              onClick={() => {
                if (voiceId !== null && voiceKey !== null) {
                  preview.toggle(voiceKey, () => edit.audio.previewUrl('voice', voiceId));
                }
              }}
            />
          </div>
          <div className="whole-field whole-field--audio" data-slot="bgm-value">
            <BgmCard
              edit={edit}
              preview={preview}
              container={container}
              open={card === 'bgm'}
              onOpenChange={(open) => setCard(open ? 'bgm' : null)}
              trigger={
                <button type="button" className="whole-field__trigger focus-ring" data-slot="bgm-change" aria-label={`${t('audio.bgm.title')} ${bgm.enabled ? track : t('audio.off')}`} disabled={edit.video === null}>
                  <span className="whole-field__name">{t('audio.bgm.title')}</span>
                  <span className="whole-field__value">{bgm.enabled ? track : t('audio.off')}</span>
                </button>
              }
            />
            <ListenButton
              name={track}
              playing={bgmKey !== null && preview.playing === bgmKey}
              disabled={bgmKey === null}
              slot="bgm-listen"
              onClick={() => {
                if (bgm.entryId !== null && bgmKey !== null) {
                  const id = bgm.entryId;
                  preview.toggle(bgmKey, () => edit.audio.previewUrl('bgm', id));
                }
              }}
            />
          </div>
        </div>
        {problem === null ? null : (
          <Notice tone="warning">
            {t(problem.kind === 'unavailable' ? 'audio.preview.unavailable' : 'audio.preview.failed')}
          </Notice>
        )}
      </section>

      <CaptionFields edit={edit} container={container} />
    </div>
  );
}

function ListenButton({ name, playing, disabled, slot, onClick }: {
  name: string;
  playing: boolean;
  disabled: boolean;
  slot: 'voice-listen' | 'bgm-listen';
  onClick: () => void;
}) {
  const { t } = useLocale();
  return (
    <IconButton
      className="whole-field__listen"
      label={t(playing ? 'audio.preview.stopNamed' : 'audio.preview.listenNamed', { name })}
      data-slot={slot}
      disabled={disabled}
      onClick={onClick}
    >
      {playing ? <Square aria-hidden fill="currentColor" /> : <Play aria-hidden fill="currentColor" className="play-glyph" />}
    </IconButton>
  );
}
