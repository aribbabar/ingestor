import { Component, type ErrorInfo, type ReactNode } from 'react'
import styles from './RouteErrorBoundary.module.css'

type RouteErrorBoundaryProps = {
  children: ReactNode
  resetKey: string
}

type RouteErrorBoundaryState = {
  error: Error | null
}

export class RouteErrorBoundary extends Component<RouteErrorBoundaryProps, RouteErrorBoundaryState> {
  state: RouteErrorBoundaryState = { error: null }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('Route render failed', error, errorInfo)
  }

  componentDidUpdate(previousProps: RouteErrorBoundaryProps) {
    if (previousProps.resetKey !== this.props.resetKey && this.state.error) {
      this.setState({ error: null })
    }
  }

  render() {
    if (!this.state.error) return this.props.children

    return (
      <main className={styles.errorPanel} aria-labelledby="route-error-title">
        <div>
          <h1 id="route-error-title">Something went wrong</h1>
          <p>This page could not render. Reload Ingestor to try again.</p>
        </div>
        <button type="button" onClick={() => window.location.reload()}>
          Reload
        </button>
      </main>
    )
  }
}
