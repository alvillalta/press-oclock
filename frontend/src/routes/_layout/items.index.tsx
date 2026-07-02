import { useSuspenseQuery } from "@tanstack/react-query"
import { createFileRoute, useNavigate } from "@tanstack/react-router"
import { Search } from "lucide-react"
import { Suspense } from "react"

import { type Mail, MailsService } from "@/client"
import { DataTable } from "@/components/Common/DataTable"
import AddItem from "@/components/Items/AddItem"
import { columns } from "@/components/Items/columns"
import PendingItems from "@/components/Pending/PendingItems"

function getItemsQueryOptions() {
  return {
    queryFn: () => MailsService.readMails({ skip: 0, limit: 100 }),
    queryKey: ["mails"],
    /* refetchInterval: 5000,
    refetchOnWindowFocus: true, */
  }
}

export const Route = createFileRoute("/_layout/items/")({
  component: ItemsIndex,
})

function ItemsTableContent() {
  const { data: items } = useSuspenseQuery(getItemsQueryOptions())
  const navigate = useNavigate()

  const handleRowClick = (mail: Mail) => {
    if (!mail.id) {
      return
    }

    navigate({ to: "/items/$mailId", params: { mailId: mail.id } })
  }

  if (items.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-center">
        <div className="mb-4 rounded-full bg-muted p-4">
          <Search className="h-8 w-8 text-muted-foreground" />
        </div>
        <h3 className="text-lg font-semibold">You don't have any mails yet</h3>
        <p className="text-muted-foreground">Ingest a new mail to get started</p>
      </div>
    )
  }

  return <DataTable columns={columns} data={items} onRowClick={handleRowClick} />
}

function ItemsTable() {
  return (
    <Suspense fallback={<PendingItems />}>
      <ItemsTableContent />
    </Suspense>
  )
}

function ItemsIndex() {
  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Correos</h1>
          <p className="text-muted-foreground">Gestiona tu bandeja de entrada</p>
        </div>
        <AddItem />
      </div>
      <ItemsTable />
    </div>
  )
}
