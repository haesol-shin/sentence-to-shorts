import { recommendedSceneCount } from '@/features/concept/model';
import { getConceptSnapshot } from '@/features/concept/store';
import type { Language } from '@/shared/api/client';
import { configureScriptMockSettings } from '@/features/script/fixture';
import { configureScriptSceneCounts, DURATIONS } from '@/features/script/model';
import { ScriptScreen } from '@/features/script/script-screen';
import type { ScriptDraftState } from '@/features/script/types';

// The concept screen owns the target length to scene count rule. The app reads
// it once here instead of keeping a second copy in the script feature.
configureScriptSceneCounts(DURATIONS.map((seconds) => recommendedSceneCount(seconds)));
configureScriptMockSettings(() => {
  const settings = getConceptSnapshot()?.document.settings;
  return settings === undefined
    ? null
    : { target_duration_s: settings.target_duration_s, scene_count: settings.format.scene_count };
});

/**
 * The script step: lines, their order and their tone, behind one confirm gate.
 * The screen takes the current video, its original script and the step change
 * as optional props so the shell can pass them without the screen owning them.
 */
export function ScriptRoute({
  videoId = null,
  serverVideoId = null,
  draftState = 'ready',
  topic = null,
  userScript = null,
  language = 'ko',
  onNext,
}: {
  videoId?: string | null;
  serverVideoId?: string | null;
  draftState?: ScriptDraftState;
  topic?: string | null;
  userScript?: string | null;
  language?: Language;
  onNext?: () => void;
}) {
  return (
    <ScriptScreen
      videoId={videoId}
      serverVideoId={serverVideoId}
      draftState={draftState}
      topic={topic}
      userScript={userScript}
      language={language}
      onNext={onNext}
    />
  );
}
