import type { IndexJob } from '../types'

export type JobProgressSummary = {
  percent: number
  label: string
  eta?: string
}

export function jobProgress(job: IndexJob): JobProgressSummary {
  const total = job.progress_total ?? 0
  const current = Math.max(0, job.progress_current)
  const percent = total > 0 ? Math.min(100, Math.round((current / total) * 100)) : 8
  const unit = job.progress_label.startsWith('http') ? 'pages' : 'files'
  const baseLabel =
    total > 0
      ? `${current} of ${total} ${unit} scanned`
      : current > 0
        ? `${current} ${unit} scanned`
        : job.status === 'cancelling'
          ? 'Cancelling'
          : 'Starting'
  const detail = job.progress_label && !job.progress_label.startsWith('Scanning ') ? ` - ${job.progress_label}` : ''
  return {
    percent,
    label: `${baseLabel}${detail}`,
    eta: formatEta(job, current, total),
  }
}

function formatEta(job: IndexJob, current: number, total: number) {
  if (total <= 0 || current <= 0 || current >= total || job.status !== 'running') return undefined
  const startedAt = new Date(job.created_at).getTime()
  if (Number.isNaN(startedAt)) return undefined
  const elapsedSeconds = Math.max(1, (Date.now() - startedAt) / 1000)
  const secondsRemaining = Math.round((elapsedSeconds / current) * (total - current))
  if (secondsRemaining < 60) return `about ${secondsRemaining}s left`
  return `about ${Math.ceil(secondsRemaining / 60)}m left`
}
