"use client";

import { useTranslations } from "next-intl";
import { Badge } from "@/components/ui/badge";
import { useSseStore } from "@/stores/sse-store";
import { ThemeToggle } from "@/components/layout/theme-toggle";
import { NotificationCenter } from "@/components/layout/notification-center";

export function Header() {
  const status = useSseStore((s) => s.status);
  const t = useTranslations("connection");

  const statusMap: Record<string, { label: string; variant: "default" | "secondary" | "destructive" }> = {
    connected: { label: t("connected"), variant: "default" },
    connecting: { label: t("connecting"), variant: "secondary" },
    disconnected: { label: t("disconnected"), variant: "destructive" },
  };
  const info = statusMap[status] ?? statusMap.disconnected;

  return (
    <header className="flex h-14 items-center justify-between border-b px-4">
      <div />
      <div className="flex items-center gap-3">
        <NotificationCenter />
        <ThemeToggle />
        <Badge variant={info.variant}>{info.label}</Badge>
      </div>
    </header>
  );
}
