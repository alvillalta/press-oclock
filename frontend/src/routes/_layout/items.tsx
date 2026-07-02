import { createFileRoute, Outlet } from "@tanstack/react-router"

export const Route = createFileRoute("/_layout/items")({
  component: Items,
  head: () => ({
    meta: [
      {
        title: "Mails - FastAPI Template",
      },
    ],
  }),
})

function Items() {
  return <Outlet />
}
