import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Trash2 } from "lucide-react"
import { useState } from "react"
import { useForm } from "react-hook-form"

import { type QuestionPublic, QuestionsService } from "@/client"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { LoadingButton } from "@/components/ui/loading-button"
import { SidebarMenuAction } from "@/components/ui/sidebar"
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"

interface DeleteQuestionProps {
  id: string
}

export function DeleteQuestion({ id }: DeleteQuestionProps) {
  const [isOpen, setIsOpen] = useState(false)
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const { handleSubmit } = useForm()

  const mutation = useMutation({
    mutationFn: () => QuestionsService.deleteQuestion({ id }),
    onSuccess: () => {
      showSuccessToast("La pregunta se eliminó correctamente")
      setIsOpen(false)
      queryClient.setQueryData<QuestionPublic[]>(["questions"], (questions) =>
        questions?.filter((question) => question.id !== id),
      )
      window.dispatchEvent(new CustomEvent("question-deleted", { detail: id }))
      queryClient.removeQueries({ queryKey: ["question", id], exact: true })
    },
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["questions"] })
    },
  })

  return (
    <Dialog open={isOpen} onOpenChange={setIsOpen}>
      <SidebarMenuAction
        type="button"
        showOnHover
        aria-label="Eliminar pregunta"
        title="Eliminar pregunta"
        onClick={(event) => {
          event.preventDefault()
          event.stopPropagation()
          setIsOpen(true)
        }}
      >
        <Trash2 aria-hidden="true" />
      </SidebarMenuAction>
      <DialogContent className="sm:max-w-md">
        <form
          onSubmit={handleSubmit(() => {
            mutation.mutate()
          })}
        >
          <DialogHeader>
            <DialogTitle>Eliminar pregunta</DialogTitle>
            <DialogDescription>
              Esta pregunta se eliminará permanentemente. ¿Estás seguro? No
              podrás deshacer esta acción.
            </DialogDescription>
          </DialogHeader>

          <DialogFooter className="mt-4">
            <DialogClose asChild>
              <Button variant="outline" disabled={mutation.isPending}>
                Cancelar
              </Button>
            </DialogClose>
            <LoadingButton
              variant="destructive"
              type="submit"
              loading={mutation.isPending}
            >
              Eliminar
            </LoadingButton>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
