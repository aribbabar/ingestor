import { NavLink } from 'react-router'
import type { ViewName } from '../../../types'
import styles from './AppHeader.module.css'

type AppHeaderProps = {
  activeView: ViewName
  apiStatus: 'checking' | 'online' | 'offline'
}

const navItems: ViewName[] = ['capture', 'sources', 'settings']
const logoSrc = `${import.meta.env.BASE_URL}logo.svg`

export function AppHeader({ activeView, apiStatus }: AppHeaderProps) {
  const statusLabel = titleCase(apiStatus)

  return (
    <header className={styles.topbar}>
      <NavLink className={styles.brand} to="/capture">
        <span className={styles.brandMark} aria-hidden="true">
          <img src={logoSrc} alt="" />
        </span>
        <span className={styles.brandName}>Ingestor</span>
      </NavLink>

      <nav className={styles.topbarNav} aria-label="Primary">
        {navItems.map((view) => (
          <NavLink
            aria-current={activeView === view ? 'page' : undefined}
            className={activeView === view ? styles.current : undefined}
            key={view}
            to={`/${view}`}
          >
            {view === 'capture' ? 'Capture' : titleCase(view)}
          </NavLink>
        ))}
      </nav>

      <div className={`${styles.statusPill} ${styles[apiStatus]}`} role="status">
        {statusLabel}
      </div>
    </header>
  )
}

function titleCase(value: string) {
  return value.charAt(0).toUpperCase() + value.slice(1)
}
