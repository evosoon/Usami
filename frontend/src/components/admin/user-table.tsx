"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogClose } from "@/components/ui/dialog";
import { UserPlus } from "lucide-react";
import { useAuthStore } from "@/stores/auth-store";
import type { AdminUser, CreateUserData } from "@/hooks/use-admin-users";

/** Read current user ID from auth store or fall back to JWT cookie. */
function useCurrentUserId(): string | undefined {
  const storeId = useAuthStore((s) => s.user?.id);
  return useMemo(() => {
    if (storeId) return storeId;
    if (typeof document === "undefined") return undefined;
    const token = document.cookie
      .split("; ")
      .find((c) => c.startsWith("access_token="))
      ?.split("=")[1];
    if (!token) return undefined;
    try {
      const payload = JSON.parse(atob(token.split(".")[1]));
      return payload.sub;
    } catch {
      return undefined;
    }
  }, [storeId]);
}

interface UserTableProps {
  users: AdminUser[];
  onCreateUser: (data: CreateUserData) => void;
  onUpdateUser: (id: string, data: { role?: string; is_active?: boolean }) => void;
  isCreating: boolean;
}

export function UserTable({ users, onCreateUser, onUpdateUser, isCreating }: UserTableProps) {
  const [newUser, setNewUser] = useState<CreateUserData>({
    email: "",
    password: "",
    display_name: "",
    role: "user",
  });
  const t = useTranslations("admin");
  const currentUserId = useCurrentUserId();

  const handleCreate = () => {
    if (!newUser.email || !newUser.password || !newUser.display_name) return;
    onCreateUser(newUser);
    setNewUser({ email: "", password: "", display_name: "", role: "user" });
  };

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <Dialog>
          <DialogTrigger render={<Button size="sm" />}>
            <UserPlus className="size-4 mr-1" />
            {t("createUser")}
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>{t("createUser")}</DialogTitle>
            </DialogHeader>
            <div className="space-y-3">
              <Input
                placeholder={t("email")}
                value={newUser.email}
                onChange={(e) => setNewUser((p) => ({ ...p, email: e.target.value }))}
              />
              <Input
                placeholder={t("displayName")}
                value={newUser.display_name}
                onChange={(e) => setNewUser((p) => ({ ...p, display_name: e.target.value }))}
              />
              <Input
                type="password"
                placeholder={t("password")}
                value={newUser.password}
                onChange={(e) => setNewUser((p) => ({ ...p, password: e.target.value }))}
              />
              <select
                className="w-full rounded-md border px-3 py-2 text-sm"
                value={newUser.role}
                onChange={(e) => setNewUser((p) => ({ ...p, role: e.target.value }))}
              >
                <option value="user">User</option>
                <option value="admin">Admin</option>
              </select>
              <DialogClose render={
                <Button className="w-full" onClick={handleCreate} disabled={isCreating} />
              }>
                {isCreating ? t("creating") : t("create")}
              </DialogClose>
            </div>
          </DialogContent>
        </Dialog>
      </div>

      <div className="rounded-md border">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b bg-muted/50">
              <th className="px-4 py-2 text-left font-medium">{t("user")}</th>
              <th className="px-4 py-2 text-left font-medium">{t("email")}</th>
              <th className="px-4 py-2 text-left font-medium">{t("role")}</th>
              <th className="px-4 py-2 text-left font-medium">{t("status")}</th>
              <th className="px-4 py-2 text-left font-medium">{t("actions")}</th>
            </tr>
          </thead>
          <tbody>
            {users.map((user) => (
              <tr key={user.id} className="border-b">
                <td className="px-4 py-2">{user.display_name}</td>
                <td className="px-4 py-2 text-muted-foreground">{user.email}</td>
                <td className="px-4 py-2">
                  <Badge variant={user.role === "admin" ? "default" : "secondary"}>
                    {user.role}
                  </Badge>
                </td>
                <td className="px-4 py-2">
                  <Badge variant={user.is_active ? "default" : "destructive"}>
                    {user.is_active ? t("active") : t("disabled")}
                  </Badge>
                </td>
                <td className="px-4 py-2 space-x-2">
                  {user.id === currentUserId ? (
                    <span className="text-xs text-muted-foreground">—</span>
                  ) : (
                    <>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() =>
                          onUpdateUser(user.id, {
                            role: user.role === "admin" ? "user" : "admin",
                          })
                        }
                      >
                        {user.role === "admin" ? t("demote") : t("promote")}
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() =>
                          onUpdateUser(user.id, { is_active: !user.is_active })
                        }
                      >
                        {user.is_active ? t("disable") : t("enable")}
                      </Button>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
