"use client";

import { useTheme } from "next-themes";
import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Sun, Moon, Monitor } from "lucide-react";
import { Button } from "@/components/ui/button";

const THEME_CYCLE = ["system", "light", "dark"] as const;
const THEME_ICON: Record<string, typeof Sun> = {
  system: Monitor,
  light: Sun,
  dark: Moon,
};

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  const t = useTranslations("settings");

  useEffect(() => setMounted(true), []);

  if (!mounted) {
    return (
      <Button variant="ghost" size="icon" className="size-8">
        <Monitor className="size-4" />
      </Button>
    );
  }

  const current = theme ?? "system";
  const Icon = THEME_ICON[current] ?? Monitor;
  const next = THEME_CYCLE[(THEME_CYCLE.indexOf(current as typeof THEME_CYCLE[number]) + 1) % THEME_CYCLE.length];

  return (
    <Button
      variant="ghost"
      size="icon"
      className="size-8"
      onClick={() => setTheme(next)}
      title={t("themeCurrent", { theme: current })}
    >
      <Icon className="size-4" />
    </Button>
  );
}
