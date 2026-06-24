import { useEffect, useId } from 'react'
import { createPortal } from 'react-dom'
import styles from './ConfirmDialog.module.css'

type ConfirmDialogProps = {
  title: string
  description: string
  confirmLabel?: string
  cancelLabel?: string
  isConfirming?: boolean
  onCancel: () => void
  onConfirm: () => void
}

export function ConfirmDialog({
  title,
  description,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  isConfirming = false,
  onCancel,
  onConfirm,
}: ConfirmDialogProps) {
  const titleId = useId()
  const descriptionId = useId()

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape' && !isConfirming) {
        onCancel()
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [isConfirming, onCancel])

  return createPortal(
    <div
      aria-labelledby={titleId}
      aria-describedby={descriptionId}
      aria-modal="true"
      className={styles.backdrop}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !isConfirming) {
          onCancel()
        }
      }}
      role="dialog"
    >
      <div className={styles.dialog}>
        <div>
          <h2 id={titleId}>{title}</h2>
          <p id={descriptionId}>{description}</p>
        </div>
        <div className={styles.actions}>
          <button className={styles.cancelButton} disabled={isConfirming} onClick={onCancel} type="button">
            {cancelLabel}
          </button>
          <button className={styles.confirmButton} disabled={isConfirming} onClick={onConfirm} type="button">
            {isConfirming ? 'Deleting...' : confirmLabel}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}
