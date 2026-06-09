import { SiteFooter } from "@/components/layout/site-footer"
import { SiteHeader } from "@/components/layout/site-header"
import { SupportWorkspace } from "@/components/support/support-workspace"

export default function Home() {
  return (
    <>
      <SiteHeader />
      <main className="flex-1">
        <SupportWorkspace />
      </main>
      <SiteFooter />
    </>
  )
}
