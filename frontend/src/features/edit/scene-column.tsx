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
      className="relative shrink-0 self-start"
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
        className={compact ? 'w-24' : 'edit-scene-card'}
      />
      {edit.unseen.includes(scene.id) ? (
        <span
          data-slot="scene-unseen"
          aria-hidden="true"
          className="absolute top-3 left-10 size-[10px] rounded-[var(--radius-pill)] bg-[var(--emphasis)]"
        />
      ) : null}
      <IconButton
        size="24"
        label={t('edit.scene.deleteLabel', { number })}
        onClick={() => edit.requestDelete(scene.id)}
        className="scene-delete"
      >
        <Trash2 aria-hidden size={14} />
      </IconButton>
      {/* This mark follows the selection even when none of the pictures are ready. */}
      {selected ? (
        <span
          aria-hidden="true"
          data-slot="scene-selected"
          className="edit-scene-selection pointer-events-none absolute inset-0 rounded-[var(--radius-content)] p-1"
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
      className="edit-scene-column hidden shrink-0 flex-col gap-3 rounded-l-[var(--radius-column)] bg-[var(--surface-muted)] pt-[26px] pr-0 pb-5 pl-[var(--layout-gutter)] md:flex"
    >
      <h2 className="edit-column-title">
        <span>{t('edit.scene.list')}</span>
      </h2>
      <ScrollPane label={t('edit.scene.list')} jumpLabel={t('shell.scroll.jump')} className="-ml-1 min-h-0 flex-1">
        <div className="flex flex-col gap-2">
          {edit.scenes.length === 0 ? (
            <p className="text-[15px] text-[var(--text-muted)]">{t('edit.scene.empty')}</p>
          ) : (
            edit.scenes.map((scene, index) => (
              <SceneCard key={scene.id} scene={scene} index={index} edit={edit} compact={false} />
            ))
          )}
        </div>
      </ScrollPane>
      <div className="flex justify-start pl-[26px]">
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
