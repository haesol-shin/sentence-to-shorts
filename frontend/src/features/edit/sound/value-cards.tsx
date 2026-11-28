import type { ReactElement } from 'react';

import { useLocale } from '@/shared/lib/i18n/locale';

import type { EditValue } from '../edit-context';
import { ChoiceDialog, type ChoiceItem } from './choice-dialog';
import { BgmDetails } from './bgm-details';
import { bgmChange, readAudio, trackPatch, tracksOfMood, VOICE_PATH } from './model';
import type { AudioPreview } from './use-audio-preview';

interface CardProps {
  edit: EditValue;
  preview: AudioPreview;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  trigger: ReactElement;
  container?: HTMLElement;
}

export function VoiceCard({ edit, preview, open, onOpenChange, trigger, container }: CardProps) {
  const { t, language } = useLocale();
  const { voiceId } = readAudio(edit.video);
  const items: ChoiceItem[] = edit.voices.map((item) => ({
    id: item.id,
    label: item.label[language],
    previewKey: `voice:${item.id}`,
    loadPreview: () => edit.audio.previewUrl('voice', item.id),
  }));

  return (
    <ChoiceDialog
      open={open}
      onOpenChange={onOpenChange}
      trigger={trigger}
      container={container}
      title={t('audio.voice.title')}
      label={t('audio.voice.pickerTitle')}
      description={t('audio.voice.pickerDescription')}
      listLabel={t('audio.voice.list')}
      emptyText={t('audio.voice.empty')}
      items={items}
      current={voiceId}
      preview={preview}
      disabled={edit.settingsBusy}
      onApply={(id) => {
        const item = edit.voices.find((entry) => entry.id === id);
        if (item === undefined) return;
        edit.applySettings([{ path: VOICE_PATH, value: { id: item.id, revision: item.revision } }]);
      }}
    />
  );
}

export function BgmCard({ edit, preview, open, onOpenChange, trigger, container }: CardProps) {
  const { t, language } = useLocale();
  const { bgm } = readAudio(edit.video);
  const canChoose = bgm.enabled && edit.bgmStatus === 'ready';
  const choices: ChoiceItem[] = tracksOfMood(edit.bgm, bgm.mood).map((item) => ({
    id: item.id,
    label: item.label[language],
    previewKey: `bgm:${item.id}`,
    loadPreview: () => edit.audio.previewUrl('bgm', item.id),
  }));

  const title = t('audio.bgm.pickerTitle', { mood: t(`audio.mood.${bgm.mood}`) });

  return (
    <ChoiceDialog
      open={open}
      onOpenChange={onOpenChange}
      trigger={trigger}
      container={container}
      title={title}
      label={title}
      description={t('audio.bgm.pickerDescription')}
      listLabel={t('audio.bgm.list')}
      emptyText={t('audio.bgm.empty')}
      items={canChoose ? choices : []}
      current={bgm.entryId}
      preview={preview}
      showList={canChoose}
      details={<BgmDetails edit={edit} preview={preview} />}
      disabled={edit.settingsBusy || !canChoose}
      onApply={(id) => {
        const picked = edit.bgm.find((item) => item.id === id);
        if (picked !== undefined) edit.applySettings(bgmChange(edit.video, trackPatch(picked)));
      }}
    />
  );
}
