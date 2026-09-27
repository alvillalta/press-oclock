import { useSuspenseQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"

import { MailsService } from "@/client"

export const Route = createFileRoute("/_layout/items/$mailId")({
  component: MailDetailPage,
  head: () => ({
    meta: [
      {
        title: "Mail Detail - FastAPI Template",
      },
    ],
  }),
})

function MailDetailPage() {
  const { mailId } = Route.useParams()

  const { data: mail } = useSuspenseQuery({
    queryKey: ["mail", mailId],
    queryFn: () => MailsService.readMail({ id: mailId }),
  })

  return (
    <article className="mx-auto w-full max-w-4xl rounded-2xl border border-border bg-card px-6 py-6 sm:px-8 sm:py-8">
      <h1 className="text-2xl font-semibold tracking-tight text-card-foreground sm:text-3xl">
        {mail.subject || "No subject"}
      </h1>

      <div className="mt-4 flex items-start justify-between gap-4 border-b border-border pb-4 text-sm text-muted-foreground">
        <p className="min-w-0 truncate">{mail.sender}</p>
        <p className="shrink-0 text-right">
          {new Date(mail.received_at).toLocaleString()}
        </p>
      </div>

      <div className="mt-6 whitespace-pre-wrap break-words text-[15px] leading-7 text-card-foreground">
        {mail.body || "(Sin contenido)"}
      </div>
    </article>
  )
}
