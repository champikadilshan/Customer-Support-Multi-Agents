import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

const badgeVariants = cva(
  "inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium capitalize transition-colors",
  {
    variants: {
      variant: {
        default: "border-transparent bg-primary text-primary-foreground",
        secondary:
          "border-transparent bg-secondary text-secondary-foreground",
        outline: "border-border bg-background text-foreground",
        muted: "border-transparent bg-muted text-muted-foreground",
        open: "border-transparent bg-foreground text-background",
        in_progress:
          "border-transparent bg-secondary text-secondary-foreground",
        resolved:
          "border-border bg-background text-foreground",
        closed: "border-transparent bg-muted text-muted-foreground",
        critical:
          "border-transparent bg-destructive text-destructive-foreground",
        high: "border-transparent bg-foreground text-background",
        medium: "border-border bg-muted text-foreground",
        low: "border-transparent bg-muted/70 text-muted-foreground",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return (
    <div className={cn(badgeVariants({ variant }), className)} {...props} />
  )
}
