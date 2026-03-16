"use client";

import { useTranslations } from "next-intl";
import { useAdminUsers, useCreateUser, useUpdateUser } from "@/hooks/use-admin-users";
import { UserTable } from "@/components/admin/user-table";
import { Skeleton } from "@/components/ui/skeleton";

export default function UsersPage() {
  const { data: users, isLoading } = useAdminUsers();
  const createUser = useCreateUser();
  const updateUser = useUpdateUser();
  const t = useTranslations("admin");

  if (isLoading) {
    return (
      <div className="p-6 space-y-4">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-[400px] w-full" />
      </div>
    );
  }

  return (
    <div className="p-6 space-y-4">
      <h1 className="text-2xl font-bold">{t("users")}</h1>
      <UserTable
        users={users ?? []}
        onCreateUser={(data) => createUser.mutate(data)}
        onUpdateUser={(id, data) => updateUser.mutate({ userId: id, ...data })}
        isCreating={createUser.isPending}
      />
    </div>
  );
}
