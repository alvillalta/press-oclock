import type { ColumnDef } from "@tanstack/react-table"

import type { Mail } from "@/client"
import { cn } from "@/lib/utils"
import { ItemActionsMenu } from "./ItemActionsMenu"

export const columns: ColumnDef<Mail>[] = [
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
        <span
          className={cn(
            "max-w-xs truncate block text-muted-foreground",
            !subject && "italic",
          )}
        >
          {subject || "No subject"}
        </span>
      )
    },
  },
  {
    accessorKey: "date",
    header: "Date",
    cell: ({ row }) => (
      <span className="text-muted-foreground">
        {new Date(row.original.date).toLocaleString()}
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
