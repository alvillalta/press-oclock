import type { ColumnDef } from "@tanstack/react-table"
import { Paperclip } from "lucide-react"

import type { MailPublic } from "@/client"
import { cn } from "@/lib/utils"
import { ItemActionsMenu } from "./ItemActionsMenu"

export const columns: ColumnDef<MailPublic>[] = [
  {
    accessorKey: "sender",
    header: "Sender",
    cell: ({ row }) => (
      <span className="font-medium">{row.original.sender}</span>
    ),
  },
  {
    accessorKey: "subject",
    header: "Subject",
    cell: ({ row }) => {
      const subject = row.original.subject
      return (
        <div className="flex min-w-0 items-center gap-2">
          <span
            className={cn(
              "max-w-xs truncate block text-muted-foreground",
              !subject && "italic",
            )}
          >
            {subject || "No subject"}
          </span>
          {row.original.has_attachments && (
            <span title="Has attachments">
              <Paperclip
                aria-label="Has attachments"
                className="size-4 shrink-0 text-muted-foreground"
              />
            </span>
          )}
        </div>
      )
    },
  },
  {
    accessorKey: "received_at",
    header: "Received",
    cell: ({ row }) => (
      <span className="text-muted-foreground">
        {new Date(row.original.received_at).toLocaleString()}
      </span>
    ),
  },
  {
    id: "actions",
    header: () => <span className="sr-only">Actions</span>,
    cell: ({ row }) => (
      <div className="flex justify-end">
        <ItemActionsMenu item={row.original} />
      </div>
    ),
  },
]
