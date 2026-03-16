"use client";

import { useTheme } from "next-themes";
import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Sun, Moon, Monitor, Globe, Bell } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { subscribeToPush, unsubscribeFromPush, isPushSubscribed } from "@/lib/push";

export default function SettingsPage() {
  const { theme, setTheme } = useTheme();
  const t = useTranslations("settings");
  const [mounted, setMounted] = useState(false);
  const [pushEnabled, setPushEnabled] = useState(false);
  const [pushLoading, setPushLoading] = useState(false);

  useEffect(() => {
    setMounted(true);
    isPushSubscribed().then(setPushEnabled);
  }, []);

  const currentLocale = typeof document !== "undefined"
    ? (document.cookie.match(/NEXT_LOCALE=(\w+)/)?.[1] ?? "zh")
    : "zh";

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
    <div className="p-6 max-w-2xl mx-auto space-y-6">
      <h1 className="text-2xl font-bold">{t("title")}</h1>

      {/* Theme */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t("theme")}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex gap-3">
            {themes.map((th) => (
              <button
                key={th.key}
                className={`flex flex-col items-center gap-2 rounded-lg border p-4 transition-colors ${
                  mounted && theme === th.key ? "border-primary bg-muted" : "hover:bg-muted/50"
                }`}
                onClick={() => setTheme(th.key)}
              >
                <th.icon className="size-5" />
                <span className="text-sm">{th.label}</span>
              </button>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Language */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <Globe className="size-4" />
            {t("language")}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex gap-3">
            {languages.map((lang) => (
              <button
                key={lang.key}
                className={`rounded-lg border px-4 py-2 text-sm transition-colors ${
                  currentLocale === lang.key ? "border-primary bg-muted" : "hover:bg-muted/50"
                }`}
                onClick={() => setLocale(lang.key)}
              >
                {lang.label}
              </button>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Notifications */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <Bell className="size-4" />
            {t("notifications")}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-between">
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
        </CardContent>
      </Card>
    </div>
  );
}
