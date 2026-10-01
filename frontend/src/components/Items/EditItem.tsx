import { Eye } from "lucide-react"
import { useState } from "react"

import type { MailPublic } from "@/client"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { DropdownMenuItem } from "@/components/ui/dropdown-menu"

interface EditItemProps {
  item: MailPublic
  onSuccess: () => void
}

const EditItem = ({ item, onSuccess }: EditItemProps) => {
  const [isOpen, setIsOpen] = useState(false)
  const handleOpenChange = (nextOpen: boolean) => {
    setIsOpen(nextOpen)
    if (!nextOpen) {
      onSuccess()
    }
  }

  return (
    <Dialog open={isOpen} onOpenChange={handleOpenChange}>
      <DropdownMenuItem
        onSelect={(e) => e.preventDefault()}
        onClick={() => setIsOpen(true)}
      >
        <Eye />
        View Mail
      </DropdownMenuItem>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Mail Details</DialogTitle>
          <DialogDescription>
            Review sender, subject and received time.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-3 py-2 text-sm">
          <p>
            <span className="font-medium">Sender:</span> {item.sender}
          </p>
          <p>
            <span className="font-medium">Subject:</span>{" "}
            {item.subject ?? "N/A"}
          </p>
          <p>
            <span className="font-medium">Received at:</span>{" "}
            {new Date(item.received_at).toLocaleString()}
          </p>
        </div>
      </DialogContent>
    </Dialog>
  )
}

export default EditItem
