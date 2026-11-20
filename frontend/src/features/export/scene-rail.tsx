import { Card } from '@/components/Card/Card';
import { ScrollPane } from '@/components/ScrollPane/ScrollPane';
import { artifactUrl, type VideoView } from '@/shared/api/client';
import { useLocale } from '@/shared/lib/i18n/locale';

/**
 * The scene column of the finished state. It uses the scene card of the edit
 * step as it is, so the white number circle and the blue unseen dot keep the
 * sizes they have there. Pressing a scene hands that scene to the caller.
 */
export function SceneRail({
  view,
  unseen,
  onPick,
}: {
  view: VideoView;
  unseen: readonly string[];
  onPick: (sceneId: string) => void;
}) {
  const { t } = useLocale();
  return (
    <aside
      data-slot="export-scenes"
      className="hidden w-[var(--layout-scene-col-w)] shrink-0 flex-col gap-2 bg-[var(--surface-muted)] p-2 md:flex"
    >
      <h2 className="px-1 text-[15px] font-bold text-[var(--text-strong)]">{t('export.scenes.list')}</h2>
      <p className="px-1 text-[13px] text-[var(--text-muted)]">{t('export.scenes.hint')}</p>
      <ScrollPane
        label={t('export.scenes.list')}
        className="max-h-[calc(100dvh-var(--layout-topbar-h)-120px)] min-h-0 flex-1"
      >
        <div className="flex flex-col items-center gap-3 pb-12">
          {view.video.scene_order.map((id, index) => {
            const scene = view.video.scenes[id];
            if (scene === undefined) return null;
            const still = view.build.scenes[id]?.still;
            const artifact = still?.state === 'fresh' ? still.artifact : null;
            return (
              <div key={id} data-slot="result-scene" data-scene-id={id} className="relative shrink-0">
                <Card
                  variant="scene"
                  label={scene.beat_label}
                  number={index + 1}
                  media={
                    artifact === null || artifact === undefined ? undefined : (
                      <img
                        data-slot="scene-still"
                        src={artifactUrl(artifact.id)}
                        alt=""
                        className="h-full w-full object-cover"
                      />
                    )
                  }
                  onClick={() => onPick(id)}
                />
                {unseen.includes(id) ? (
                  <span
                    data-slot="scene-unseen"
                    aria-hidden="true"
                    className="absolute top-3 left-[calc(var(--space-8)+var(--space-24)+var(--space-4))] size-[10px] rounded-[var(--radius-pill)] bg-[var(--emphasis)]"
                  />
                ) : null}
              </div>
            );
          })}
        </div>
      </ScrollPane>
    </aside>
  );
}
