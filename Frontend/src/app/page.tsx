import {
  PageActions,
  PageHeader,
  PageHeaderDescription,
  PageHeaderHeading,
} from "@/components/layout/page-header"
import { SiteFooter } from "@/components/layout/site-footer"
import { SiteHeader } from "@/components/layout/site-header"
import { SupportWorkspace } from "@/components/support/support-workspace"
import { Button } from "@/components/ui/button"

export default function Home() {
  return (
    <>
      <SiteHeader />
      <main className="flex-1">
        <SupportWorkspace
          header={
            <PageHeader className="pb-4 pt-1 md:pb-6 md:pt-1">
              <PageHeaderHeading>
                Customer support that feels human, powered by AI.
              </PageHeaderHeading>
              <PageHeaderDescription>
                Ask about billing, explore products, or raise a complaint — our
                multi-agent system routes you to the right specialist instantly.
              </PageHeaderDescription>
              <PageActions>
                <Button size="sm">Get Started</Button>
                <Button size="sm" variant="ghost">
                  GitHub
                </Button>
              </PageActions>
            </PageHeader>
          }
        />
      </main>
      <SiteFooter />
    </>
  )
}
