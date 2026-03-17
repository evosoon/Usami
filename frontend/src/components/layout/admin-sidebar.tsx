"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import {
  LayoutDashboard,
  Users,
  Bot,
  Wrench,
  Clock,
  HeartPulse,
  MessageSquare,
} from "lucide-react";
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarFooter,
} from "@/components/ui/sidebar";

export function AdminSidebar() {
  const pathname = usePathname();
  const t = useTranslations("admin");
  const tn = useTranslations("nav");

  const adminNav = [
    { label: t("overview"), href: "/admin/dashboard", icon: LayoutDashboard },
    { label: t("users"), href: "/admin/users", icon: Users },
    { label: t("personas"), href: "/admin/personas", icon: Bot },
    { label: t("tools"), href: "/admin/tools", icon: Wrench },
    { label: t("scheduler"), href: "/admin/scheduler", icon: Clock },
    { label: t("health"), href: "/admin/health", icon: HeartPulse },
  ];

  return (
    <Sidebar>
      <SidebarHeader>
        <Link href="/admin/dashboard" className="flex items-center gap-2 px-2 py-1">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/logo.svg" alt="Usami" className="size-6" />
          <span className="text-lg font-bold">USAMI Admin</span>
        </Link>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>{t("management")}</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {adminNav.map((item) => (
                <SidebarMenuItem key={item.href}>
                  <SidebarMenuButton
                    render={<Link href={item.href} />}
                    isActive={pathname.startsWith(item.href)}
                  >
                    <item.icon className="size-4" />
                    <span>{item.label}</span>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
      <SidebarFooter>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton render={<Link href="/chat" />}>
              <MessageSquare className="size-4" />
              <span>{tn("backToChat")}</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>
    </Sidebar>
  );
}
