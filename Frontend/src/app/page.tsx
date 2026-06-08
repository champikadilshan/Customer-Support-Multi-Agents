import {
  PageActions,
  PageHeader,
  PageHeaderDescription,
  PageHeaderHeading,
} from "@/components/layout/page-header"
import { SiteFooter } from "@/components/layout/site-footer"
import { SiteHeader } from "@/components/layout/site-header"
import { SupportChat } from "@/components/support/support-chat"
import { TicketsPanel } from "@/components/support/tickets-panel"
import { Button } from "@/components/ui/button"

export default function Home() {
  return (
    <>
      <SiteHeader />
      <main className="flex-1">
        <div className="container grid grid-cols-1 gap-8 pt-1 md:grid-cols-2">
          <div className="flex flex-col">
            <PageHeader className="pb-4 pt-0 md:pb-6 md:pt-0">
              <PageHeaderHeading>
                Build beautiful AI apps in hours, not days.
              </PageHeaderHeading>
              <PageHeaderDescription>
                Beautifully designed chatbot components based on shadcn/ui.
                Fully customizable and owned by you.
              </PageHeaderDescription>
              <PageActions>
                <Button size="sm">Get Started</Button>
                <Button size="sm" variant="ghost">
                  GitHub
                </Button>
              </PageActions>
            </PageHeader>

            <section className="px-4 pb-0">
              <SupportChat />
            </section>
          </div>

          <aside aria-label="Tickets panel" className="mt-12 hidden px-4 md:block">
            <TicketsPanel />
          </aside>
        </div>
      </main>
      <SiteFooter />
    </>
  )
}
