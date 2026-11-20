import { Button } from '@/components/Button/Button';
import { ScrollPane } from '@/components/ScrollPane/ScrollPane';
import { useLocale } from '@/shared/lib/i18n/locale';

import type { EditValue } from '../edit-context';
import { BgmSection } from './bgm-section';
import { useAudioPreview } from './use-audio-preview';
import { VoiceSection } from './voice-section';

/**
 * Voice, BGM and the sound effect rule. A scene's own effects are added and
 * checked in its scene form; this tab holds the values of the whole video.
 */
export function SoundTab({ edit }: { edit: EditValue }) {
  const { t } = useLocale();
  const preview = useAudioPreview();

  return (
    <ScrollPane label={t('audio.sound.label')} className="min-h-0 flex-1">
      <div data-slot="sound-tab" className="flex flex-col gap-5 pb-16">
        <div className="flex justify-end">
          <Button variant="ghost" disabled={!edit.canUndo || edit.settingsBusy} onClick={edit.undo}>
            {t('edit.scene.undo')}
          </Button>
        </div>
        <VoiceSection edit={edit} preview={preview} />
        <BgmSection edit={edit} preview={preview} />
        <section data-slot="sfx-section" className="flex flex-col gap-1">
          <h3 className="text-[15px] font-bold text-[var(--text-strong)]">{t('audio.sfx.title')}</h3>
          <p className="text-[15px] text-[var(--text)]">{t('audio.sfx.rule')}</p>
          <p className="text-[13px] text-[var(--text-muted)]">{t('audio.sfx.where')}</p>
        </section>
      </div>
    </ScrollPane>
  );
}
