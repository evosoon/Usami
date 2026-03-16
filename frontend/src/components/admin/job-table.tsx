"use client";

import { useTranslations } from "next-intl";
import { Badge } from "@/components/ui/badge";
import type { SchedulerJob } from "@/types/api";

interface JobTableProps {
  jobs: SchedulerJob[];
}

export function JobTable({ jobs }: JobTableProps) {
  const t = useTranslations("admin");

  return (
    <div className="overflow-x-auto rounded-md border">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b bg-muted/50">
            <th className="px-4 py-2 text-left font-medium">ID</th>
            <th className="px-4 py-2 text-left font-medium">{t("name")}</th>
            <th className="px-4 py-2 text-left font-medium">{t("nextRun")}</th>
          </tr>
        </thead>
        <tbody>
          {jobs.length === 0 ? (
            <tr>
              <td colSpan={3} className="px-4 py-8 text-center text-muted-foreground">
                {t("noJobs")}
              </td>
            </tr>
          ) : (
            jobs.map((job) => (
              <tr key={job.id} className="border-b">
                <td className="px-4 py-2 font-mono text-xs">{job.id}</td>
                <td className="px-4 py-2">{job.name}</td>
                <td className="px-4 py-2 text-muted-foreground">
                  {new Date(job.next_run_time).toLocaleString()}
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
