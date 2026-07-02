import { Eye } from "lucide-react"
import { useState } from "react"

import type { Mail } from "@/client"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { DropdownMenuItem } from "@/components/ui/dropdown-menu"

interface EditItemProps {
  item: Mail
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
          <DialogDescription>Review sender, subject and date.</DialogDescription>
        </DialogHeader>
        <div className="grid gap-3 py-2 text-sm">
          <p>
            <span className="font-medium">Sender:</span> {item.sender}
          </p>
          <p>
            <span className="font-medium">Subject:</span> {item.subject ?? "N/A"}
          </p>
          <p>
            <span className="font-medium">Date:</span>{" "}
            {new Date(item.date).toLocaleString()}
          </p>
        </div>
      </DialogContent>
    </Dialog>
  )
}

export default EditItem
