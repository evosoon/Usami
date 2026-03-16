"use client";

import { useTranslations } from "next-intl";
import { Badge } from "@/components/ui/badge";
import { useWsStore } from "@/stores/ws-store";
import { ThemeToggle } from "@/components/layout/theme-toggle";
import { NotificationCenter } from "@/components/layout/notification-center";

export function AdminHeader() {
  const status = useWsStore((s) => s.status);
  const t = useTranslations("ws");
  const ta = useTranslations("admin");

  const statusMap: Record<string, { label: string; variant: "default" | "secondary" | "destructive" }> = {
    connected: { label: t("connected"), variant: "default" },
    connecting: { label: t("connecting"), variant: "secondary" },
    disconnected: { label: t("disconnected"), variant: "destructive" },
  };
  const info = statusMap[status] ?? statusMap.disconnected;

  return (
    <header className="flex h-14 items-center justify-between border-b px-4">
      <h1 className="text-sm font-semibold text-muted-foreground">{ta("title")}</h1>
      <div className="flex items-center gap-3">
        <NotificationCenter />
        <ThemeToggle />
        <Badge variant={info.variant}>{info.label}</Badge>
      </div>
    </header>
  );
}
