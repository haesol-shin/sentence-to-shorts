import { forwardRef } from 'react';

import { Button } from '@/components/Button/Button';
import { Tooltip } from '@/components/Tooltip/Tooltip';
import type { VideoView } from '@/shared/api/client';
import { useLocale, type Translate } from '@/shared/lib/i18n/locale';

import { useActivityUnsent } from './activity';
import { downloadUrl, type Metrics } from './api';
import { startDownload } from './download';
import { formatCost, formatSpan, srtReady, type JobUsage, type TokenCounts } from './model';

const CAPTION_KEYS = {
  sentence: 'export.fact.captionSentence',
  phrase: 'export.fact.captionPhrase',
  typewriter: 'export.fact.captionTypewriter',
} as const;

function lengthText(t: Translate, seconds: number | null, exact: boolean): string {
  if (seconds === null) return t('export.fact.unknown');
  return t(exact ? 'export.fact.lengthExact' : 'export.fact.lengthApprox', { seconds: Math.round(seconds) });
}

function spanText(t: Translate, ms: number): string {
  const { minutes, seconds } = formatSpan(ms);
  return minutes > 0
    ? t('export.usage.minutesSeconds', { minutes, seconds })
    : t('export.usage.seconds', { seconds });
}

/** The caption file button: a text button in the fact line, named for the file's use only. */
function CaptionSave({ view }: { view: VideoView }) {
  const { t } = useLocale();
  const ready = srtReady(view);
  const button = (
    <Button
      variant="ghost"
      size="sm"
      className="export-facts__inline"
      disabled={!ready}
      onClick={() => startDownload(downloadUrl(view.video.id, 'srt'))}
    >
      {t('export.caption.save')}
    </Button>
  );
  return ready ? (
    <Tooltip content={t('export.caption.saveReason')} side="top">
      {button}
    </Tooltip>
  ) : (
    <Tooltip content={t('export.caption.saveReason')} side="top">
      <span tabIndex={0} className="inline-flex">
        {button}
      </span>
    </Tooltip>
  );
}

/** The four fact lines of a finished video, stacked from the top. */
export function ResultFacts({
  view,
  seconds,
  exact,
  tokens,
  onShowUsage,
}: {
  view: VideoView;
  /** The length in seconds, or null when nothing knows it yet. */
  seconds: number | null;
  /** True once the file itself told the length. */
  exact: boolean;
  tokens: TokenCounts | null;
  onShowUsage: () => void;
}) {
  const { t, language } = useLocale();
  const caption = CAPTION_KEYS[view.video.settings.caption.mode] ?? CAPTION_KEYS.sentence;
  return (
    <dl data-slot="result-facts" className="export-facts">
      <dt>{t('export.fact.length')}</dt>
      <dd>{lengthText(t, seconds, exact)}</dd>
      <dt>{t('export.fact.format')}</dt>
      <dd>{t('export.fact.formatValue')}</dd>
      <dt>{t('export.fact.caption')}</dt>
      <dd>
        {t(caption)}
        <CaptionSave view={view} />
      </dd>
      <dt>{t('export.fact.usage')}</dt>
      <dd>
        {tokens !== null
          ? t('export.fact.usageValue', {
              input: tokens.input.toLocaleString(language),
              output: tokens.output.toLocaleString(language),
            })
          : t('export.fact.unknown')}
        <Button variant="ghost" size="sm" className="export-facts__inline" onClick={onShowUsage}>
          {t('export.fact.usageOpen')}
        </Button>
      </dd>
    </dl>
  );
}

/** Where the time went and what the model calls used. What nobody measured says 미확인. */
export const UsageSection = forwardRef<HTMLElement, {
  videoId: string;
  metrics: Metrics | null;
  measured: JobUsage;
  tokens: TokenCounts | null;
}>(
  function UsageSection({ videoId, metrics, measured, tokens }, ref) {
    const { t, language } = useLocale();
    const unknown = t('export.fact.unknown');
    const unsent = useActivityUnsent(videoId);
    const { durationMs, rebuiltCount } = measured;
    return (
      <section ref={ref} tabIndex={-1} data-slot="export-usage" className="export-section">
        <h3 className="export-section__title">{t('export.usage.title')}</h3>
        {unsent && <p role="status" className="export-muted">{t('export.usage.unsent')}</p>}
        <dl className="export-facts">
          <dt>{t('export.usage.active')}</dt>
          <dd>{metrics === null ? unknown : spanText(t, metrics.active_ms)}</dd>
          <dt>{t('export.usage.waiting')}</dt>
          <dd>{metrics === null ? unknown : spanText(t, metrics.waiting_ms)}</dd>
          <dt>{t('export.usage.build')}</dt>
          <dd>{durationMs === null ? unknown : spanText(t, durationMs)}</dd>
          <dt>{t('export.usage.tokens')}</dt>
          <dd>
            {tokens !== null
              ? t('export.fact.usageValue', {
                  input: tokens.input.toLocaleString(language),
                  output: tokens.output.toLocaleString(language),
                })
              : unknown}
          </dd>
          <dt>{t('export.usage.cost')}</dt>
          <dd data-slot="usage-cost">
            {metrics === null || metrics.cost_micro_usd === null ? unknown : formatCost(metrics.cost_micro_usd)}
          </dd>
          <dt>{t('export.usage.rebuilt')}</dt>
          <dd>
            {rebuiltCount === null
              ? unknown
              : rebuiltCount === 0
                ? t('export.usage.rebuiltNone')
                : t('export.usage.rebuiltValue', { count: rebuiltCount })}
          </dd>
        </dl>
      </section>
    );
  },
);

/** The credit lines a CC BY track needs next to the video. */
export function Attribution({ view }: { view: VideoView }) {
  const { t, language } = useLocale();
  if (view.build.attribution.length === 0) return null;
  return (
    <section data-slot="export-attribution" className="export-section">
      <h3 className="export-section__title">{t('export.attribution.title')}</h3>
      <ul className="export-section__list">
        {view.build.attribution.map((line, index) => (
          <li key={`${index}-${line.ko}`}>{line[language]}</li>
        ))}
      </ul>
    </section>
  );
}
