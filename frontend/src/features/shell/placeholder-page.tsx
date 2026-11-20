import { PageHeader } from "@/components/ui/page-header"

export function PlaceholderPage({
  title,
  description,
}: {
  title: string
  description: string
}) {
  return (
    <section>
      <PageHeader title={title} description={description} />
      <div className="rounded-lg border border-dashed border-border bg-card p-8 text-sm text-muted-foreground">
        Em construção.
      </div>
    </section>
  )
}
