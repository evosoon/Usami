"use client";

import { Badge } from "@/components/ui/badge";
import { useWsStore } from "@/stores/ws-store";

const STATUS_MAP: Record<string, { label: string; variant: "default" | "secondary" | "destructive" }> = {
  connected: { label: "已连接", variant: "default" },
  connecting: { label: "连接中...", variant: "secondary" },
  disconnected: { label: "已断开", variant: "destructive" },
};

export function Header() {
  const status = useWsStore((s) => s.status);
  const info = STATUS_MAP[status] ?? STATUS_MAP.disconnected;

  return (
    <header className="flex h-14 items-center justify-between border-b px-4">
      <div />
      <div className="flex items-center gap-3">
        <Badge variant={info.variant}>{info.label}</Badge>
      </div>
    </header>
  );
}
