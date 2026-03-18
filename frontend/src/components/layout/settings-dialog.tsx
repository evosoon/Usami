"use client";

import { useTheme } from "next-themes";
import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Sun, Moon, Monitor, Globe, Bell, X } from "lucide-react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { subscribeToPush, unsubscribeFromPush, isPushSubscribed } from "@/lib/push";
import { cn } from "@/lib/utils";

interface SettingsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function SettingsDialog({ open, onOpenChange }: SettingsDialogProps) {
  const { theme, setTheme } = useTheme();
  const t = useTranslations("settings");
  const [mounted, setMounted] = useState(false);
  const [currentLocale, setCurrentLocale] = useState("zh");
  const [pushEnabled, setPushEnabled] = useState(false);
  const [pushLoading, setPushLoading] = useState(false);

  useEffect(() => {
    setMounted(true);
    const locale = document.cookie.match(/NEXT_LOCALE=(\w+)/)?.[1] ?? "zh";
    setCurrentLocale(locale);
    isPushSubscribed().then(setPushEnabled);
  }, []);

  const setLocale = (locale: string) => {
    document.cookie = `NEXT_LOCALE=${locale};path=/;max-age=${60 * 60 * 24 * 365}`;
    window.location.reload();
  };

  const handlePushToggle = async () => {
    setPushLoading(true);
    try {
      if (pushEnabled) {
        await unsubscribeFromPush();
        setPushEnabled(false);
      } else {
        const success = await subscribeToPush();
        setPushEnabled(success);
      }
    } finally {
      setPushLoading(false);
    }
  };

  const themes = [
    { key: "system", label: t("themeSystem"), icon: Monitor },
    { key: "light", label: t("themeLight"), icon: Sun },
    { key: "dark", label: t("themeDark"), icon: Moon },
  ];

  const languages = [
    { key: "zh", label: "中文" },
    { key: "en", label: "English" },
  ];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="sm:max-w-md bg-background/80 backdrop-blur-xl border-border/50"
        showCloseButton={false}
      >
        <DialogHeader className="flex flex-row items-center justify-between">
          <DialogTitle>{t("title")}</DialogTitle>
          <Button
            variant="ghost"
            size="icon"
            className="size-8"
            onClick={() => onOpenChange(false)}
          >
            <X className="size-4" />
          </Button>
        </DialogHeader>

        <div className="space-y-6 py-2">
          {/* Theme */}
          <div className="space-y-3">
            <h3 className="text-sm font-medium">{t("theme")}</h3>
            <div className="flex gap-2">
              {themes.map((th) => (
                <button
                  key={th.key}
                  className={cn(
                    "flex flex-1 flex-col items-center gap-2 rounded-lg border p-3 transition-colors cursor-pointer",
                    mounted && theme === th.key
                      ? "border-primary bg-primary/10"
                      : "border-border/50 hover:bg-muted/50"
                  )}
                  onClick={() => setTheme(th.key)}
                >
                  <th.icon className="size-5" />
                  <span className="text-xs">{th.label}</span>
                </button>
              ))}
            </div>
          </div>

          <Separator />

          {/* Language */}
          <div className="space-y-3">
            <h3 className="text-sm font-medium flex items-center gap-2">
              <Globe className="size-4" />
              {t("language")}
            </h3>
            <div className="flex gap-2">
              {languages.map((lang) => (
                <button
                  key={lang.key}
                  className={cn(
                    "flex-1 rounded-lg border px-4 py-2 text-sm transition-colors cursor-pointer",
                    mounted && currentLocale === lang.key
                      ? "border-primary bg-primary/10"
                      : "border-border/50 hover:bg-muted/50"
                  )}
                  onClick={() => setLocale(lang.key)}
                >
                  {lang.label}
                </button>
              ))}
            </div>
          </div>

          <Separator />

          {/* Notifications */}
          <div className="space-y-3">
            <h3 className="text-sm font-medium flex items-center gap-2">
              <Bell className="size-4" />
              {t("notifications")}
            </h3>
            <div className="flex items-center justify-between rounded-lg border border-border/50 p-3">
              <div>
                <p className="text-sm">{t("pushNotifications")}</p>
                <Badge variant={pushEnabled ? "default" : "secondary"} className="mt-1">
                  {pushEnabled ? t("pushEnabled") : t("pushDisabled")}
                </Badge>
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={handlePushToggle}
                disabled={pushLoading}
              >
                {pushLoading ? "..." : pushEnabled ? t("pushDisabled") : t("enablePush")}
              </Button>
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
