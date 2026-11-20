import { Button } from '@/components/Button/Button';
import { Notice } from '@/components/Notice/Notice';
import type { VideoView } from '@/shared/api/client';
import { useLocale } from '@/shared/lib/i18n/locale';

import type { PrecheckReport } from './api';
import { sceneNumberOf } from './model';
import type { PrecheckStatus } from './store';

/** A scene by its number; `withLine` adds its first line so an assumption can be found. */
function SceneRef({ view, id, withLine = false }: { view: VideoView; id: string; withLine?: boolean }) {
  const { t } = useLocale();
  const number = sceneNumberOf(view, id);
  const line = view.video.scenes[id]?.lines[0]?.display_text;
  if (number === 0) return <span>{id}</span>;
  return (
    <span>
      {t('export.scene.number', { number })}
      {!withLine || line === undefined || line === '' ? null : ` · ${line}`}
    </span>
  );
}

/**
 * What a viewer will take from the video, shown before it is made: the promise
 * on the first screen, the answer at the end, each statement of fact against
 * its source and the lines written as assumptions. It does not check facts.
 */
export function PrecheckPanel({
  view,
  status,
  report,
  starting,
  startFailed,
  onRetry,
  onStart,
  onEdit,
}: {
  view: VideoView;
  status: PrecheckStatus;
  report: PrecheckReport | null;
  starting: boolean;
  startFailed: boolean;
  onRetry: () => void;
  onStart: () => void;
  onEdit: () => void;
}) {
  const { t } = useLocale();
  const confirmed = view.video.stage === 'scenes_confirmed';
  return (
    <section data-slot="precheck" aria-labelledby="export-precheck-title" className="export-precheck">
      <div className="export-precheck__head">
        <h2 id="export-precheck-title" className="export-title">
          {t('export.precheck.title')}
        </h2>
        <div className="export-actions">
          {confirmed && status === 'failed' ? (
            <Button variant="ghost" onClick={onRetry}>
              {t('export.precheck.retry')}
            </Button>
          ) : null}
          <Button variant="secondary" onClick={onEdit}>
            {t('export.toEdit')}
          </Button>
          {confirmed ? (
            <Button data-slot="export-start" disabled={report === null || starting} onClick={onStart}>
              {t('export.start.make')}
            </Button>
          ) : null}
        </div>
      </div>
      {!confirmed ? <Notice>{t('export.start.blocked')}</Notice> : null}
      {confirmed && status === 'running' ? (
        <p role="status" className="export-muted">
          {t('export.precheck.running')}
        </p>
      ) : null}
      {confirmed && status === 'failed' ? (
        <Notice tone="error">{t('export.precheck.failed')}</Notice>
      ) : null}
      {report === null ? null : (
        <dl data-slot="precheck-report" className="export-report">
          <dt>{t('export.precheck.opening')}</dt>
          <dd data-slot="precheck-opening">{report.opening_promise}</dd>
          <dt>{t('export.precheck.ending')}</dt>
          <dd data-slot="precheck-ending">{report.ending_answer}</dd>
          <dt>{t('export.precheck.claims')}</dt>
          <dd data-slot="precheck-claims">
            {report.claims.length === 0 ? (
              t('export.precheck.noClaims')
            ) : (
              <ul className="export-section__list">
                {report.claims.map((claim, index) => {
                  const source = view.video.material.find((material) => material.id === claim.material_id)?.text;
                  const excerpt = source === undefined ? null : Array.from(source).slice(0, 160).join('');
                  return (
                    <li key={`${index}-${claim.scene_id}`}>
                      <SceneRef view={view} id={claim.scene_id} />
                      <span className="export-muted">
                        {` · ${claim.text} · `}
                        {excerpt === null
                          ? t('export.precheck.claimNoMaterial')
                          : t('export.precheck.claimMaterial', { text: excerpt === source ? excerpt : `${excerpt}…` })}
                      </span>
                    </li>
                  );
                })}
              </ul>
            )}
          </dd>
          <dt>{t('export.precheck.assumption')}</dt>
          <dd data-slot="precheck-assumptions">
            {report.hypotheticals.length === 0 ? (
              t('export.precheck.noAssumption')
            ) : (
              <ul className="export-section__list">
                {report.hypotheticals.map((id) => (
                  <li key={id}>
                    <SceneRef view={view} id={id} withLine />
                  </li>
                ))}
              </ul>
            )}
          </dd>
        </dl>
      )}
      <Notice tone="warning">{t('export.precheck.noGuarantee')}</Notice>
      {startFailed ? <Notice tone="error">{t('export.start.failed')}</Notice> : null}
    </section>
  );
}
