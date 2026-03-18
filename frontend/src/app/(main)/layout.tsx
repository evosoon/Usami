import { TooltipProvider } from "@/components/ui/tooltip";
import { BottomDock } from "@/components/layout/bottom-dock";

export default function MainLayout({ children }: { children: React.ReactNode }) {
  return (
    <TooltipProvider>
      <div className="relative flex h-screen w-full flex-col">
        {/* Gradient background */}
        <div className="fixed inset-0 -z-10 bg-gradient-to-br from-violet-500/20 via-background to-cyan-500/20 dark:from-violet-500/10 dark:to-cyan-500/10" />
        <div className="fixed top-0 right-0 -z-10 h-[500px] w-[500px] bg-[radial-gradient(circle,_var(--tw-gradient-stops))] from-pink-400/30 via-transparent to-transparent dark:from-pink-500/20 blur-3xl" />
        {/* Main content area - reserve bottom space for Dock */}
        <main className="flex-1 overflow-hidden pb-20">{children}</main>
        {/* Bottom Dock */}
        <BottomDock />
      </div>
    </TooltipProvider>
  );
}
