import { useEffect, useId, useRef } from 'react'
import { createPortal } from 'react-dom'
import styles from './ConfirmDialog.module.css'

type ConfirmDialogProps = {
  title: string
  description: string
  confirmLabel?: string
  confirmBusyLabel?: string
  cancelLabel?: string
  isConfirming?: boolean
  onCancel: () => void
  onConfirm: () => void
}

export function ConfirmDialog({
  title,
  description,
  confirmLabel = 'Confirm',
  confirmBusyLabel,
  cancelLabel = 'Cancel',
  isConfirming = false,
  onCancel,
  onConfirm,
}: ConfirmDialogProps) {
  const titleId = useId()
  const descriptionId = useId()
  const dialogRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const previousActiveElement = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const firstFocusable = getFocusableElements(dialogRef.current).at(0)
    firstFocusable?.focus()

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape' && !isConfirming) {
        onCancel()
        return
      }

      if (event.key !== 'Tab') return

      const focusableElements = getFocusableElements(dialogRef.current)
      if (!focusableElements.length) {
        event.preventDefault()
        return
      }

      const firstElement = focusableElements[0]
      const lastElement = focusableElements.at(-1)
      if (!lastElement) return

      if (event.shiftKey && document.activeElement === firstElement) {
        event.preventDefault()
        lastElement.focus()
      } else if (!event.shiftKey && document.activeElement === lastElement) {
        event.preventDefault()
        firstElement.focus()
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('keydown', handleKeyDown)
      previousActiveElement?.focus()
    }
  }, [isConfirming, onCancel])

  return createPortal(
    <div
      aria-label={title}
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
      <div className={styles.dialog} ref={dialogRef}>
        <div>
          <h2 id={titleId}>{title}</h2>
          <p id={descriptionId}>{description}</p>
        </div>
        <div className={styles.actions}>
          <button className={styles.cancelButton} disabled={isConfirming} onClick={onCancel} type="button">
            {cancelLabel}
          </button>
          <button className={styles.confirmButton} disabled={isConfirming} onClick={onConfirm} type="button">
            {isConfirming ? confirmBusyLabel ?? `${confirmLabel}...` : confirmLabel}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}

function getFocusableElements(root: HTMLElement | null) {
  if (!root) return []
  return Array.from(
    root.querySelectorAll<HTMLElement>(
      'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    ),
  )
}
