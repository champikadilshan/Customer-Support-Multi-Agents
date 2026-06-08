const NAV_ITEMS = ["Demo", "Docs", "Components", "Themes"]

export function MainNav() {
  return (
    <div className="mr-4 hidden md:flex">
      <div className="mr-4 flex items-center space-x-2 lg:mr-6">
        <span className="hidden font-bold lg:inline-block">shadcn-chatbot-kit</span>
      </div>
      <nav className="flex items-center gap-4 text-sm lg:gap-6">
        {NAV_ITEMS.map((item) => (
          <span
            key={item}
            className="cursor-default text-foreground/60 transition-colors hover:text-foreground/80"
          >
            {item}
          </span>
        ))}
      </nav>
    </div>
  )
}
