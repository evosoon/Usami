"use client";

import { useTranslations } from "next-intl";
import { Badge } from "@/components/ui/badge";
import type { ToolInfo } from "@/types/api";

interface ToolTableProps {
  tools: ToolInfo[];
}

export function ToolTable({ tools }: ToolTableProps) {
  const t = useTranslations("admin");

  return (
    <div className="overflow-x-auto rounded-md border">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b bg-muted/50">
            <th className="px-4 py-2 text-left font-medium">{t("name")}</th>
            <th className="px-4 py-2 text-left font-medium">{t("description")}</th>
            <th className="px-4 py-2 text-left font-medium">{t("source")}</th>
            <th className="px-4 py-2 text-left font-medium">{t("permissionLevel")}</th>
          </tr>
        </thead>
        <tbody>
          {tools.map((tool) => (
            <tr key={tool.name} className="border-b">
              <td className="px-4 py-2 font-mono text-xs">{tool.name}</td>
              <td className="px-4 py-2 text-muted-foreground">{tool.description}</td>
              <td className="px-4 py-2">
                <Badge variant="secondary">{tool.source}</Badge>
              </td>
              <td className="px-4 py-2">
                <Badge variant="outline">L{tool.permission_level}</Badge>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
