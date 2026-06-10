import { Icons } from "@/components/icons"

export function SiteFooter() {
  return (
    <footer className="-mt-4 w-full pb-4 pt-0 md:px-8">
      <div className="container flex w-full max-w-screen-2xl justify-center">
        <p className="text-balance text-center text-sm leading-loose text-muted-foreground">
          <span>Built by</span>{" "}
          <Icons.blazity className="mx-1 inline-block h-4 w-4 align-[-2px]" />
          <span>
            <span className="font-medium text-blazity underline underline-offset-4">
              Blazity
            </span>
            , based on a project by{" "}
            <span className="font-medium underline underline-offset-4">
              shadcn
            </span>
            . The source code is available on{" "}
            <span className="font-medium underline underline-offset-4">
              GitHub
            </span>
            .
          </span>
        </p>
      </div>
    </footer>
  )
}
