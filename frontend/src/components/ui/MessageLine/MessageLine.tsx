import type { Message } from '../../../types'
import { classNames } from '../../../utils/classNames'
import styles from './MessageLine.module.css'

export function MessageLine({ message }: { message: Message }) {
  if (!message) return null
  return <p className={classNames(styles.message, message.tone && styles[message.tone])}>{message.text}</p>
}
