import type { SourceMode } from '../../../types'
import styles from './ModeTabs.module.css'

export function ModeTabs({ mode, onModeChange }: { mode: SourceMode; onModeChange: (mode: SourceMode) => void }) {
  return (
    <div className={styles.tabs} role="tablist" aria-label="Source type">
      <button
        aria-selected={mode === 'local'}
        className={mode === 'local' ? styles.active : undefined}
        onClick={() => onModeChange('local')}
        role="tab"
        type="button"
      >
        Local docs
      </button>
      <button
        aria-selected={mode === 'web'}
        className={mode === 'web' ? styles.active : undefined}
        onClick={() => onModeChange('web')}
        role="tab"
        type="button"
      >
        Web docs
      </button>
    </div>
  )
}
