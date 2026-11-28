import { useState } from 'react';
import { Sparkles } from 'lucide-react';

import { Button } from '@/components/Button/Button';
import { CloseButton } from '@/components/CloseButton/CloseButton';
import { Notice } from '@/components/Notice/Notice';
import { SettingsRow } from '@/components/SettingsRow/SettingsRow';
import { Switch } from '@/components/Switch/Switch';
import { ValueField } from '@/components/ValueField/ValueField';
import { useLocale } from '@/shared/lib/i18n/locale';

import type { Mood } from '../api';
import type { EditValue } from '../edit-context';
import {
  BGM_GAINS,
  bgmChange,
  bgmGainLabel,
  MOODS,
  moodPatch,
  readAudio,
} from './model';
import type { AudioPreview } from './use-audio-preview';
export function BgmDetails({ edit, preview }: { edit: EditValue; preview: AudioPreview }) {
  const { t } = useLocale();
  const [missingMood, setMissingMood] = useState(false);
  const work = edit.bgmWork;
  const { bgm } = readAudio(edit.video);
  const off = !bgm.enabled || edit.settingsBusy;
  const catalogReady = edit.bgmStatus === 'ready';


  const moodItems = MOODS.map((mood) => ({ value: mood, label: t(`audio.mood.${mood}`) }));
  const gainValues = BGM_GAINS.includes(bgm.gain) ? BGM_GAINS : [...BGM_GAINS, bgm.gain];
  const gainItems = gainValues.map((value) => ({
    value: String(value),
    label: bgmGainLabel(t, value),
  }));

  return (
    <section data-slot="bgm-section" className="flex flex-col gap-1">

      <SettingsRow
        label={t('audio.bgm.switch')}
        control={
          <Switch
            label={t('audio.bgm.switch')}
            checked={bgm.enabled}
            disabled={edit.settingsBusy}
            onCheckedChange={(next) => {
              if (!next) preview.stop();
              edit.applySettings(bgmChange(edit.video, { enabled: next }));
            }}
          >
            {t(bgm.enabled ? 'audio.on' : 'audio.off')}
          </Switch>
        }
      />

      <SettingsRow
        label={t('audio.bgm.mood')}
        control={
          <ValueField
            label={t('audio.bgm.mood')}
            items={moodItems}
            value={bgm.mood}
            disabled={off || !catalogReady}
            onValueChange={(value) => {
              const patch = moodPatch(edit.bgm, value as Mood, bgm);
              setMissingMood(patch === null && value !== bgm.mood);
              if (patch !== null) {
                preview.stop();
                edit.applySettings(bgmChange(edit.video, patch));
              }
            }}
          />
        }
      />
      {edit.bgmStatus === 'loading' ? <Notice>{t('audio.bgm.loading')}</Notice> : null}
      {edit.bgmStatus === 'failed' || (catalogReady && missingMood) ? (
        <div className="flex flex-wrap items-center gap-2">
          <Notice tone="error">
            {t(edit.bgmStatus === 'failed' ? 'audio.bgm.error.catalog' : 'audio.bgm.empty')}
          </Notice>
          <Button variant="ghost" onClick={() => {
            setMissingMood(false);
            void edit.audio.reloadBgm().catch(() => { /* The catalog state carries the failure. */ });
          }}>
            {t('audio.bgm.reload')}
          </Button>
        </div>
      ) : null}

      <SettingsRow
        label={t('audio.bgm.gain')}
        control={
          <ValueField
            label={t('audio.bgm.gain')}
            items={gainItems}
            value={String(bgm.gain)}
            disabled={off}
            onValueChange={(value) =>
              edit.applySettings(bgmChange(edit.video, { gain_db_x10: Number(value) }))
            }
          />
        }
      />

      <SettingsRow
        label={t('audio.bgm.ducking')}
        description={t('audio.bgm.duckingHelp')}
        control={
          <Switch
            label={t('audio.bgm.ducking')}
            checked={bgm.ducking}
            disabled={off}
            onCheckedChange={(next) => edit.applySettings(bgmChange(edit.video, { ducking: next }))}
          >
            {t(bgm.ducking ? 'audio.on' : 'audio.off')}
          </Switch>
        }
      />

      <p className="text-[13px] text-[var(--text-muted)]">{t('audio.bgm.uploadHelp')}</p>

      <SettingsRow
        label={t('audio.bgm.generate')}
        description={t('audio.bgm.generateHelp', { mood: t(`audio.mood.${bgm.mood}`) })}
        control={
          <Button
            variant="ghost"
            data-slot="bgm-generate"
            iconStart={<Sparkles aria-hidden size={16} />}
            disabled={work.running === 'code'
              ? work.stopping
              : edit.settingsBusy || work.running !== null || work.waitingToApply}
            running={work.running === 'code'}
            stopLabel={t(work.stopping ? 'audio.bgm.stopping' : 'audio.bgm.stop')}
            onStop={work.stop}
            onClick={work.generate}
          >
            {t('audio.bgm.generateButton')}
          </Button>
        }
      />

      {work.waitingToApply ? <Notice>{t('audio.bgm.waitingToApply')}</Notice> : null}
      {work.error?.kind !== 'code' ? null : (
        <div className="flex items-start gap-2" data-slot="bgm-error">
          <Notice tone="error">{t(work.error.key)}</Notice>
          <CloseButton label={t('audio.bgm.dismiss')} onClick={work.dismiss} />
        </div>
      )}
    </section>
  );
}
