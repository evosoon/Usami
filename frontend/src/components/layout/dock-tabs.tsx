"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import { MessageSquare } from "lucide-react";
import { cn } from "@/lib/utils";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

interface DockTab {
  key: string;
  href: string;
  icon: typeof MessageSquare;
  labelKey: string;
}

const DOCK_TABS: DockTab[] = [
  { key: "chat", href: "/chat", icon: MessageSquare, labelKey: "chat" },
  // Reserved for future modules
  // { key: "explore", href: "/explore", icon: Sparkles, labelKey: "explore" },
];

export function DockTabs() {
  const pathname = usePathname();
  const t = useTranslations("nav");

  return (
    <div className="flex items-center gap-1">
      {DOCK_TABS.map((tab) => {
        const isActive = pathname.startsWith(tab.href);
        const Icon = tab.icon;

        return (
          <Tooltip key={tab.key}>
            <TooltipTrigger
              render={
                <Link
                  href={tab.href}
                  className={cn(
                    "flex items-center justify-center rounded-xl p-2.5 transition-all",
                    "hover:bg-muted hover:scale-110",
                    "active:scale-95",
                    isActive && "bg-primary text-primary-foreground hover:bg-primary/90"
                  )}
                />
              }
            >
              <Icon className="size-5" />
            </TooltipTrigger>
            <TooltipContent side="top">{t(tab.labelKey)}</TooltipContent>
          </Tooltip>
        );
      })}
    </div>
  );
}
