import { createFileRoute, Outlet } from "@tanstack/react-router"

export const Route = createFileRoute("/_layout/items")({
  component: Items,
  head: () => ({
    meta: [
      {
        title: "Mails - Press O'clock",
      },
    ],
  }),
})

function Items() {
  return <Outlet />
}
