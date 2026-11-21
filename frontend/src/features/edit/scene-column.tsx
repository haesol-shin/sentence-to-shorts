import { Plus, Trash2 } from 'lucide-react';

import { Card } from '@/components/Card/Card';
import { IconButton } from '@/components/IconButton/IconButton';
import { ScrollPane } from '@/components/ScrollPane/ScrollPane';
import { useLocale } from '@/shared/lib/i18n/locale';

import { artifactUrl } from './api';
import type { EditValue } from './edit-context';
import { estimatedSeconds, stillIsReady, type Scene } from './model';

function SceneCard({
  scene,
  index,
  edit,
  compact,
}: {
  scene: Scene;
  index: number;
  edit: EditValue;
  compact: boolean;
}) {
  const { t } = useLocale();
  const selected = scene.id === edit.selectedId;
  const number = index + 1;
  const still = edit.build?.scenes[scene.id]?.still;
  const media =
    stillIsReady(edit.build, scene.id) && still?.artifact !== null && still?.artifact !== undefined ? (
      <img
        data-slot="scene-still"
        src={artifactUrl(still.artifact.id)}
        alt=""
        className="h-full w-full object-cover"
      />
    ) : undefined;

  return (
    <div
      data-slot="scene-card"
      data-scene-id={scene.id}
      className="relative shrink-0"
      draggable
      onDragStart={(event) => {
        event.dataTransfer.effectAllowed = 'move';
        event.dataTransfer.setData('text/plain', scene.id);
      }}
      onDragOver={(event) => event.preventDefault()}
      onDrop={(event) => {
        event.preventDefault();
        const moved = event.dataTransfer.getData('text/plain');
        if (moved !== '' && moved !== scene.id) {
          edit.requestReorderTo(moved, index);
        }
      }}
    >
      <Card
        variant="scene"
        label={scene.beat_label}
        media={media}
        number={number}
        duration={t('edit.scene.estimated', { seconds: estimatedSeconds(scene) })}
        selected={selected}
        busy={edit.phase === 'stills'}
        busyLabel={t('edit.scene.busy')}
        onClick={() => edit.selectScene(scene.id)}
        className={compact ? 'w-24' : undefined}
      />
      {edit.unseen.includes(scene.id) ? (
        <span
          data-slot="scene-unseen"
          aria-hidden="true"
          className="absolute top-3 left-[calc(var(--space-8)+var(--space-24)+var(--space-4))] size-[10px] rounded-[var(--radius-pill)] bg-[var(--emphasis)]"
        />
      ) : null}
      <IconButton
        label={t('edit.scene.deleteLabel', { number })}
        onClick={() => edit.requestDelete(scene.id)}
        className="absolute top-1 right-1 z-10"
      >
        <Trash2 aria-hidden size={16} />
      </IconButton>
      {selected ? (
        <span
          aria-hidden="true"
          data-slot="scene-selected-mark"
          className="pointer-events-none absolute inset-0 rounded-[var(--radius-content)] ring-2 ring-[var(--ring)]"
        />
      ) : null}
    </div>
  );
}

export function SceneColumn({ edit }: { edit: EditValue }) {
  const { t } = useLocale();
  return (
    <aside
      data-slot="scene-column"
      className="hidden w-[var(--layout-scene-col-w)] shrink-0 flex-col gap-2 bg-[var(--surface-muted)] p-2 md:flex"
    >
      <h2 className="px-1 text-[15px] font-bold text-[var(--text-strong)]">
        {t('edit.scene.list')}
      </h2>
      <ScrollPane label={t('edit.scene.list')} jumpLabel={t('shell.scroll.jump')} className="min-h-0 flex-1">
        <div className="flex flex-col items-center gap-3 pb-12">
          {edit.scenes.length === 0 ? (
            <p className="px-1 text-[15px] text-[var(--text-muted)]">{t('edit.scene.empty')}</p>
          ) : (
            edit.scenes.map((scene, index) => (
              <SceneCard key={scene.id} scene={scene} index={index} edit={edit} compact={false} />
            ))
          )}
        </div>
      </ScrollPane>
      <div className="flex justify-center">
        <IconButton label={t('edit.scene.add')} onClick={edit.requestAdd}>
          <Plus aria-hidden size={20} />
        </IconButton>
      </div>
    </aside>
  );
}

export function SceneStrip({ edit }: { edit: EditValue }) {
  const { t } = useLocale();
  return (
    <div
      data-slot="scene-strip"
      aria-label={t('edit.scene.list')}
      className="flex w-full shrink-0 items-center gap-2 overflow-x-auto p-2 md:hidden"
    >
      {edit.scenes.length === 0 ? (
        <p className="shrink-0 px-1 text-[15px] text-[var(--text-muted)]">{t('edit.scene.empty')}</p>
      ) : (
        edit.scenes.map((scene, index) => (
          <div key={scene.id} className="shrink-0">
            <SceneCard scene={scene} index={index} edit={edit} compact />
          </div>
        ))
      )}
      <IconButton label={t('edit.scene.add')} onClick={edit.requestAdd} className="shrink-0">
        <Plus aria-hidden size={20} />
      </IconButton>
    </div>
  );
}
