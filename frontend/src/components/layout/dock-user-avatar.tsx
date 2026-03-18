"use client";

import { useState } from "react";
import { useAuthStore } from "@/stores/auth-store";
import { useIsMobile } from "@/hooks/use-mobile";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { UserProfileCard } from "@/components/layout/user-profile-card";
import { SettingsDialog } from "@/components/layout/settings-dialog";
import { cn } from "@/lib/utils";

export function DockUserAvatar() {
  const [popoverOpen, setPopoverOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const user = useAuthStore((s) => s.user);
  const isMobile = useIsMobile();

  // Get user initials as fallback
  const initials =
    user?.display_name
      ?.split(" ")
      .map((n) => n[0])
      .join("")
      .toUpperCase()
      .slice(0, 2) || "U";

  const avatarElement = (
    <Avatar size="default">
      <AvatarImage src="/logo.svg" alt="Usami" />
      <AvatarFallback>{initials}</AvatarFallback>
    </Avatar>
  );

  const handleOpenSettings = () => {
    setPopoverOpen(false);
    setSettingsOpen(true);
  };

  // Mobile: click to open sheet from bottom
  if (isMobile) {
    return (
      <>
        <Sheet>
          <SheetTrigger
            render={
              <button
                className={cn(
                  "relative rounded-full transition-all cursor-pointer",
                  "hover:scale-110 hover:ring-2 hover:ring-primary/50",
                  "active:scale-95"
                )}
              />
            }
          >
            {avatarElement}
          </SheetTrigger>
          <SheetContent side="bottom" className="h-auto rounded-t-2xl">
            <UserProfileCard onOpenSettings={handleOpenSettings} />
          </SheetContent>
        </Sheet>
        <SettingsDialog open={settingsOpen} onOpenChange={setSettingsOpen} />
      </>
    );
  }

  // Desktop: hover shows user profile card in Popover
  return (
    <>
      <Popover open={popoverOpen} onOpenChange={setPopoverOpen}>
        <PopoverTrigger
          openOnHover
          delay={150}
          render={
            <button
              className={cn(
                "relative rounded-full transition-all cursor-pointer",
                "hover:scale-110 hover:ring-2 hover:ring-primary/50",
                "active:scale-95"
              )}
            />
          }
        >
          {avatarElement}
        </PopoverTrigger>
        <PopoverContent
          side="top"
          sideOffset={12}
          className="w-72"
        >
          <UserProfileCard onOpenSettings={handleOpenSettings} />
        </PopoverContent>
      </Popover>
      <SettingsDialog open={settingsOpen} onOpenChange={setSettingsOpen} />
    </>
  );
}
