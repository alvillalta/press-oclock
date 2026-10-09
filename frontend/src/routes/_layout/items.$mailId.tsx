import { useQuery, useSuspenseQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { Download, Eye, Paperclip } from "lucide-react"
import { useState } from "react"

import { type AttachmentPublic, MailsService } from "@/client"
import { Button } from "@/components/ui/button"

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

      {(mail.attachments ?? []).length > 0 && (
        <section
          className="mt-5 space-y-3"
          aria-labelledby="attachments-heading"
        >
          <h2
            id="attachments-heading"
            className="flex items-center gap-2 text-sm font-semibold text-card-foreground"
          >
            <Paperclip className="size-4" />
            Archivos adjuntos
          </h2>
          <div className="space-y-2">
            {(mail.attachments ?? []).map((attachment) => (
              <AttachmentCard
                key={attachment.id}
                mailId={mail.id}
                attachment={attachment}
              />
            ))}
          </div>
        </section>
      )}

      <div className="mt-6 whitespace-pre-wrap break-words text-[15px] leading-7 text-card-foreground">
        {mail.body || "(Sin contenido)"}
      </div>
    </article>
  )
}

function AttachmentCard({
  mailId,
  attachment,
}: {
  mailId: string
  attachment: AttachmentPublic
}) {
  const [showText, setShowText] = useState(false)
  const extension = attachment.filename.split(".").pop()?.toLowerCase()
  const isPdf = extension === "pdf"
  const isText = extension === "txt"
  const previewText = useQuery({
    queryKey: ["mail-attachment-text", mailId, attachment.id],
    queryFn: () =>
      MailsService.readMailAttachmentText({
        mailId,
        attachmentId: attachment.id,
      }),
    enabled: isText && showText,
  })

  const openStoredFile = async (download: boolean) => {
    const newWindow = window.open("about:blank", "_blank")
    try {
      const signedUrl = await MailsService.getMailAttachmentSignedUrl({
        mailId,
        attachmentId: attachment.id,
        download,
      })
      if (newWindow) {
        newWindow.opener = null
        newWindow.location.href = signedUrl.url
      } else {
        window.location.assign(signedUrl.url)
      }
    } catch {
      newWindow?.close()
    }
  }

  const handleAction = () => {
    if (isPdf) {
      void openStoredFile(false)
      return
    }
    if (isText) {
      setShowText((current) => !current)
      return
    }
    void openStoredFile(true)
  }

  return (
    <div className="rounded-lg border border-border bg-background px-4 py-3">
      <div className="flex min-w-0 items-center justify-between gap-4">
        <div className="flex min-w-0 items-center gap-3">
          <Paperclip className="size-4 shrink-0 text-muted-foreground" />
          <div className="min-w-0">
            <p
              className="truncate text-sm font-medium"
              title={attachment.filename}
            >
              {attachment.filename}
            </p>
            <p className="text-xs text-muted-foreground">
              {attachment.mime_type}
            </p>
          </div>
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={handleAction}
          aria-expanded={isText ? showText : undefined}
        >
          {isPdf || isText ? <Eye /> : <Download />}
          {isText && showText
            ? "Ocultar"
            : isPdf || isText
              ? "Ver"
              : "Descargar"}
        </Button>
      </div>
      {isText && showText && (
        <div className="mt-3 max-h-80 overflow-auto rounded-md bg-muted/40 p-3">
          {previewText.isLoading ? (
            <p className="text-sm text-muted-foreground">Cargando texto…</p>
          ) : previewText.isError ? (
            <p className="text-sm text-destructive">
              No se pudo cargar el fichero.
            </p>
          ) : (
            <pre className="whitespace-pre-wrap break-words text-sm leading-6">
              {previewText.data || "(Sin contenido)"}
            </pre>
          )}
        </div>
      )}
    </div>
  )
}
