import { classNames } from '../../../utils/classNames'
import styles from './Badge.module.css'

type BadgeProps = {
  value: string
  variant?: string
}

export function Badge({ value, variant = 'neutral' }: BadgeProps) {
  return <span className={classNames(styles.badge, styles[variant])}>{value}</span>
}
