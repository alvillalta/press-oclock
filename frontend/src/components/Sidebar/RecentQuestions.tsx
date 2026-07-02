import { useQuery } from "@tanstack/react-query"
import { Link as RouterLink } from "@tanstack/react-router"

import { type Question, QuestionsService } from "@/client"
import {
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar"

const MAX_VISIBLE_QUESTION_CHARS = 30

function truncateQuestion(text: string) {
  if (text.length <= MAX_VISIBLE_QUESTION_CHARS) {
    return text
  }

  return `${text.slice(0, MAX_VISIBLE_QUESTION_CHARS)}...`
}

function getQuestionsQueryOptions() {
  return {
    queryFn: () => QuestionsService.readQuestions({ skip: 0, limit: 50 }),
    queryKey: ["questions"],
    refetchOnWindowFocus: true,
  }
}

export function RecentQuestions() {
  const { isMobile, setOpenMobile } = useSidebar()
  const { data: questions = [] } = useQuery(getQuestionsQueryOptions())

  const handleQuestionClick = () => {
    if (isMobile) {
      setOpenMobile(false)
    }
  }

  const sortedQuestions = [...questions].sort((a, b) => {
    const createdAtA = a.created_at ? new Date(a.created_at).getTime() : 0
    const createdAtB = b.created_at ? new Date(b.created_at).getTime() : 0

    return createdAtB - createdAtA
  })

  if (sortedQuestions.length === 0) {
    return null
  }

  return (
    <SidebarGroup>
      <SidebarGroupLabel>Recientes</SidebarGroupLabel>
      <SidebarGroupContent>
        <SidebarMenu>
          {sortedQuestions.map((question: Question, index) => {
            const itemKey = question.id ?? `${question.question}-${index}`

            return (
              <SidebarMenuItem key={itemKey}>
                <SidebarMenuButton
                  tooltip={question.question}
                  className="cursor-pointer"
                  asChild
                >
                  <RouterLink
                    to="/"
                    search={{ questionId: question.id ?? "" }}
                    onClick={handleQuestionClick}
                  >
                    <span>{truncateQuestion(question.question)}</span>
                  </RouterLink>
                </SidebarMenuButton>
              </SidebarMenuItem>
            )
          })}
        </SidebarMenu>
      </SidebarGroupContent>
    </SidebarGroup>
  )
}

export default RecentQuestions