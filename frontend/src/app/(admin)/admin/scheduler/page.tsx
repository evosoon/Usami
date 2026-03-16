import { getTranslations } from "next-intl/server";
import { serverApi } from "@/lib/api-server";
import { JobTable } from "@/components/admin/job-table";

export const dynamic = "force-dynamic";

export default async function SchedulerPage() {
  const jobs = await serverApi.getJobs();
  const t = await getTranslations("admin");

  return (
    <div className="p-6 space-y-4">
      <h1 className="text-2xl font-bold">{t("scheduler")}</h1>
      <JobTable jobs={jobs} />
    </div>
  );
}
