"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { Settings, Shield, LogOut, Wifi, WifiOff } from "lucide-react";
import { useAuthStore } from "@/stores/auth-store";
import { useSseStore } from "@/stores/sse-store";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Badge } from "@/components/ui/badge";
import { ThemeToggle } from "@/components/layout/theme-toggle";

interface UserProfileCardProps {
  onOpenSettings?: () => void;
}

export function UserProfileCard({ onOpenSettings }: UserProfileCardProps) {
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const status = useSseStore((s) => s.status);
  const t = useTranslations();

  const isAdmin = user?.role === "admin";
  const initials =
    user?.display_name
      ?.split(" ")
      .map((n) => n[0])
      .join("")
      .toUpperCase()
      .slice(0, 2) || "U";

  const statusInfo = {
    connected: { icon: Wifi, variant: "default" as const, label: t("connection.connected") },
    connecting: { icon: Wifi, variant: "secondary" as const, label: t("connection.connecting") },
    disconnected: { icon: WifiOff, variant: "destructive" as const, label: t("connection.disconnected") },
  }[status] ?? { icon: WifiOff, variant: "destructive" as const, label: t("connection.disconnected") };

  return (
    <div className="flex flex-col gap-3">
      {/* User info section */}
      <div className="flex items-center gap-3">
        <Avatar size="default">
          <AvatarFallback>{initials}</AvatarFallback>
        </Avatar>
        <div className="flex-1 min-w-0">
          <p className="font-medium truncate text-sm">{user?.display_name || t("userCard.guest")}</p>
          <p className="text-xs text-muted-foreground truncate">{user?.email}</p>
        </div>
        <ThemeToggle />
      </div>

      {/* SSE connection status */}
      <div className="flex items-center justify-between">
        <span className="text-xs text-muted-foreground">{t("userCard.connectionStatus")}</span>
        <Badge variant={statusInfo.variant} className="gap-1 text-xs">
          <statusInfo.icon className="size-3" />
          {statusInfo.label}
        </Badge>
      </div>

      <Separator />

      {/* Menu items */}
      <div className="flex flex-col gap-1">
        <Button
          variant="ghost"
          size="sm"
          className="justify-start h-8"
          onClick={onOpenSettings}
        >
          <Settings className="size-4" />
          {t("nav.settings")}
        </Button>

        {isAdmin && (
          <Button
            variant="ghost"
            size="sm"
            className="justify-start h-8"
            render={<Link href="/admin/dashboard" />}
          >
            <Shield className="size-4" />
            {t("nav.admin")}
          </Button>
        )}
      </div>

      <Separator />

      {/* Logout */}
      <Button
        variant="ghost"
        size="sm"
        className="justify-start h-8 text-destructive hover:text-destructive"
        onClick={logout}
      >
        <LogOut className="size-4" />
        {t("common.logout")}
      </Button>
    </div>
  );
}
