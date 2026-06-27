import { ChevronDown } from 'lucide-react'
import { useEffect, useId, useRef, useState } from 'react'
import styles from './SelectControl.module.css'

export type SelectOption<T extends string> = {
  value: T
  label: string
  description?: string
}

type SelectControlProps<T extends string> = {
  id?: string
  value: T
  options: SelectOption<T>[]
  disabled?: boolean
  placeholder?: string
  onChange: (value: T) => void
}

export function SelectControl<T extends string>({
  id,
  value,
  options,
  disabled = false,
  placeholder = 'Select an option',
  onChange,
}: SelectControlProps<T>) {
  const generatedId = useId()
  const buttonId = id ?? generatedId
  const listboxId = `${buttonId}-listbox`
  const rootRef = useRef<HTMLDivElement>(null)
  const [isOpen, setIsOpen] = useState(false)
  const selectedOption = options.find((option) => option.value === value)

  useEffect(() => {
    if (!isOpen) return

    function closeOnOutsideClick(event: MouseEvent) {
      if (!rootRef.current?.contains(event.target as Node)) {
        setIsOpen(false)
      }
    }

    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        setIsOpen(false)
      }
    }

    document.addEventListener('mousedown', closeOnOutsideClick)
    document.addEventListener('keydown', closeOnEscape)
    return () => {
      document.removeEventListener('mousedown', closeOnOutsideClick)
      document.removeEventListener('keydown', closeOnEscape)
    }
  }, [isOpen])

  function choose(option: SelectOption<T>) {
    onChange(option.value)
    setIsOpen(false)
  }

  function moveSelection(direction: 1 | -1) {
    const currentIndex = Math.max(
      0,
      options.findIndex((option) => option.value === value),
    )
    const nextIndex = (currentIndex + direction + options.length) % options.length
    onChange(options[nextIndex].value)
  }

  return (
    <div className={styles.selectControl} ref={rootRef}>
      <button
        aria-controls={listboxId}
        aria-expanded={isOpen}
        className={styles.trigger}
        disabled={disabled || !options.length}
        id={buttonId}
        onClick={() => setIsOpen((current) => !current)}
        onKeyDown={(event) => {
          if (event.key === 'ArrowDown') {
            event.preventDefault()
            if (!isOpen) setIsOpen(true)
            moveSelection(1)
          }
          if (event.key === 'ArrowUp') {
            event.preventDefault()
            if (!isOpen) setIsOpen(true)
            moveSelection(-1)
          }
        }}
        type="button"
      >
        <span className={selectedOption ? styles.triggerText : styles.placeholder}>
          {selectedOption?.label ?? placeholder}
        </span>
        <ChevronDown aria-hidden="true" size={16} />
      </button>

      {isOpen ? (
        <div className={styles.menu} id={listboxId} role="listbox">
          {options.map((option) => (
            <button
              aria-label={option.label}
              aria-selected={option.value === value}
              className={option.value === value ? styles.optionSelected : undefined}
              key={option.value}
              onClick={() => choose(option)}
              role="option"
              title={option.description}
              type="button"
            >
              <span>{option.label}</span>
              {option.description ? <small>{option.description}</small> : null}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  )
}
