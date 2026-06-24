import styles from './PageHeading.module.css'

export function PageHeading({ title, text }: { title: string; text: string }) {
  return (
    <section className={styles.heading}>
      <h1>{title}</h1>
      <p>{text}</p>
    </section>
  )
}
