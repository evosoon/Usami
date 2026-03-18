"use client";

import { cn } from "@/lib/utils";
import { useIsMobile } from "@/hooks/use-mobile";
import { DockUserAvatar } from "@/components/layout/dock-user-avatar";
import { DockTabs } from "@/components/layout/dock-tabs";
import { DockNotification } from "@/components/layout/dock-notification";

export function BottomDock() {
  const isMobile = useIsMobile();

  return (
    <nav
      className={cn(
        // Dock base style: centered, rounded, shadow, translucent background
        "fixed bottom-4 left-1/2 -translate-x-1/2 z-50",
        "flex items-center gap-1 px-2 py-1.5",
        "min-w-[680px]",
        "rounded-2xl border border-border/50",
        "bg-white/50 dark:bg-zinc-900/50 backdrop-blur-xl",
        "shadow-lg",
        // Mobile: full width, closer to bottom
        isMobile && "bottom-2 left-2 right-2 translate-x-0 min-w-0 justify-between"
      )}
    >
      <DockUserAvatar />
      <div className="h-6 w-px bg-border/50 mx-1" />
      <DockTabs />
      <div className="ml-auto">
        <DockNotification />
      </div>
    </nav>
  );
}
