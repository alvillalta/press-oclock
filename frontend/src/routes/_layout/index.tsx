import { createFileRoute } from "@tanstack/react-router"
import { useNavigate } from "@tanstack/react-router"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useCallback, useEffect, useMemo, useState } from "react"
import { z } from "zod"

import { MailsService, type Question, QuestionsService } from "@/client"

type QuestionSource = {
  mail_id: string
  chunk_text: string
  sender: string
  subject: string
  date: string
}

const dashboardSearchSchema = z.object({
  questionId: z.string().optional().catch(undefined),
})

export const Route = createFileRoute("/_layout/")({
  component: Dashboard,
  validateSearch: dashboardSearchSchema,
  head: () => ({
    meta: [
      {
        title: "Dashboard - Press O'clock",
      },
    ],
  }),
})

function Dashboard() {
  const { questionId } = Route.useSearch()
  const navigate = useNavigate()
  const [questionInput, setQuestionInput] = useState("")
  const [submittedQuestion, setSubmittedQuestion] = useState<string | null>(null)
  const [dotCount, setDotCount] = useState(0)
  const queryClient = useQueryClient()

  const selectedQuestion = useQuery({
    queryKey: ["question", questionId],
    queryFn: () => QuestionsService.readQuestion({ id: questionId ?? "" }),
    enabled: Boolean(questionId),
  })

  const mutation = useMutation({
    mutationFn: (question: string) => QuestionsService.createQuestion({ questionIn: question }),
    onSuccess: (createdQuestion) => {
      queryClient.setQueryData<Question[]>(["questions"], (currentQuestions = []) => {
        const filteredQuestions = currentQuestions.filter(
          (question) => question.id !== createdQuestion.id,
        )

        return [createdQuestion, ...filteredQuestions]
      })
      queryClient.invalidateQueries({ queryKey: ["questions"] })
    },
  })

  const isProcessing = mutation.isPending || selectedQuestion.isLoading

  useEffect(() => {
    if (!isProcessing) {
      setDotCount(0)
      return
    }

    const intervalId = window.setInterval(() => {
      setDotCount((current) => (current + 1) % 4)
    }, 450)

    return () => {
      window.clearInterval(intervalId)
    }
  }, [isProcessing])

  const displayedQuestion = selectedQuestion.data ?? mutation.data

  useEffect(() => {
    if (selectedQuestion.data?.question) {
      setSubmittedQuestion(selectedQuestion.data.question)
    }
  }, [selectedQuestion.data])

  const mappedSources = useMemo<QuestionSource[]>(() => {
    const rawSources = displayedQuestion?.sources
    if (!rawSources) {
      return []
    }

    return rawSources.slice(0, 3).map((source) => {
      const sourceRecord = source as Record<string, unknown>
      return {
        mail_id: String(sourceRecord.mail_id ?? ""),
        chunk_text: String(sourceRecord.chunk_text ?? ""),
        sender: String(sourceRecord.sender ?? ""),
        subject: String(sourceRecord.subject ?? ""),
        date: String(sourceRecord.date ?? ""),
      }
    })
  }, [displayedQuestion])

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()

    const trimmedQuestion = questionInput.trim()
    if (!trimmedQuestion) {
      return
    }

    setSubmittedQuestion(trimmedQuestion)
    mutation.mutate(trimmedQuestion)
  }

  const handleSourceClick = async (mailId: string) => {
    if (!mailId) {
      return
    }

    await queryClient.fetchQuery({
      queryKey: ["mail", mailId],
      queryFn: () => MailsService.readMail({ id: mailId }),
    })

    navigate({ to: "/items/$mailId", params: { mailId } })
  }

  const resetToInitialLayout = useCallback(() => {
    setSubmittedQuestion(null)
    setQuestionInput("")
    setDotCount(0)
    mutation.reset()
  }, [mutation])

  useEffect(() => {
    const handleDashboardReset = () => {
      resetToInitialLayout()
    }

    window.addEventListener("dashboard-reset", handleDashboardReset)
    return () => {
      window.removeEventListener("dashboard-reset", handleDashboardReset)
    }
  }, [resetToInitialLayout])

  const truncatedSubject = (subject: string) => {
    if (subject.length <= 30) {
      return subject
    }
    return `${subject.slice(0, 30)}...`
  }

  const processingDots = ".".repeat(dotCount)
  const hasSubmittedQuestion = submittedQuestion !== null || Boolean(questionId)
  const displayedQuestionText = submittedQuestion ?? selectedQuestion.data?.question ?? ""

  return (
    <div className="mx-auto w-full max-w-4xl px-4 py-8 sm:px-6 lg:px-8">
      {!hasSubmittedQuestion ? (
        <div className="flex min-h-[70vh] flex-col items-center justify-center">
          <h1 className="mb-6 text-center text-3xl font-semibold tracking-tight">
            Consulta lo que quieras sobre tus correos
          </h1>
          <form onSubmit={handleSubmit} className="w-full max-w-2xl">
            <input
              autoFocus
              type="text"
              value={questionInput}
              onChange={(event) => setQuestionInput(event.target.value)}
              placeholder="Escribe tu pregunta y pulsa Enter"
              className="h-12 w-full rounded-xl border border-input bg-background px-4 text-base shadow-sm outline-none transition-colors focus-visible:border-primary"
            />
          </form>
        </div>
      ) : (
        <div className="flex min-h-[70vh] flex-col">
          <div className="mb-8 flex justify-end">
            <div className="max-w-[80%] rounded-2xl bg-muted px-4 py-3 text-sm leading-relaxed text-foreground sm:text-base">
              {displayedQuestionText}
            </div>
          </div>

          {isProcessing ? (
            <div className="max-w-3xl text-left text-muted-foreground">
              <span className="font-medium text-foreground">Procesando</span>
              <span className="inline-block w-8">{processingDots}</span>
            </div>
          ) : mutation.isError || selectedQuestion.isError ? (
            <div className="max-w-3xl text-left text-sm text-destructive">
              No se pudo procesar la pregunta. Intenta de nuevo.
            </div>
          ) : displayedQuestion ? (
            <div className="max-w-3xl space-y-6 text-left">
              <div className="rounded-2xl border border-border bg-card px-5 py-4 leading-relaxed text-card-foreground">
                {displayedQuestion.answer}
              </div>

              {mappedSources.length > 0 && (
                <div className="rounded-2xl border border-border bg-muted/40 p-4">
                  <div className="space-y-4">
                    {mappedSources.map((source, index) => (
                      <button
                        type="button"
                        key={`${source.sender}-${source.date}-${index}`}
                        onClick={() => handleSourceClick(source.mail_id)}
                        className="w-full rounded-xl border border-border bg-background p-4 text-left transition-colors hover:bg-muted/40"
                      >
                        <p className="text-sm leading-relaxed text-foreground sm:text-base">
                          {source.chunk_text}
                        </p>
                        <div className="mt-3 space-y-1 text-xs text-muted-foreground">
                          <p>sender: {source.sender || "-"}</p>
                          <p>subject: {truncatedSubject(source.subject || "-")}</p>
                          <p>date: {source.date || "-"}</p>
                        </div>
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ) : null}
        </div>
      )}
      <div className="sr-only" aria-live="polite">
        {mutation.isPending ? "Procesando pregunta" : ""}
      </div>
    </div>
  )
}
