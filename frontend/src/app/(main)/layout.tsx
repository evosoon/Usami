import { TooltipProvider } from "@/components/ui/tooltip";
import { BottomDock } from "@/components/layout/bottom-dock";

export default function MainLayout({ children }: { children: React.ReactNode }) {
  return (
    <TooltipProvider>
      <div className="relative flex h-screen w-full flex-col">
        {/* Background */}
        <div className="fixed inset-0 -z-10">
          {/* Light mode: premium neutral gradient with texture */}
          <div className="absolute inset-0 bg-gradient-to-br from-stone-100 via-zinc-50 to-slate-100 dark:hidden" />
          <div className="absolute inset-0 bg-gradient-to-tr from-amber-500/[0.03] via-transparent to-sky-500/[0.05] dark:hidden" />
          <div className="absolute top-[-10%] left-[-5%] h-[500px] w-[500px] rounded-full bg-gradient-to-br from-rose-200/40 to-transparent blur-3xl animate-float dark:hidden" />
          <div className="absolute bottom-[-10%] right-[-5%] h-[600px] w-[600px] rounded-full bg-gradient-to-tl from-sky-200/30 to-transparent blur-3xl animate-float-delayed dark:hidden" />

          {/* Dark mode: original violet-cyan gradient */}
          <div className="absolute inset-0 hidden dark:block bg-gradient-to-br from-violet-500/10 via-background to-cyan-500/10" />
          <div className="absolute top-0 right-0 hidden dark:block h-[500px] w-[500px] bg-[radial-gradient(circle,_var(--tw-gradient-stops))] from-pink-500/20 via-transparent to-transparent blur-3xl" />

          {/* Shared: noise texture */}
          <div className="absolute inset-0 opacity-[0.015] dark:opacity-[0.03]" style={{
            backgroundImage: `url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)'/%3E%3C/svg%3E")`,
          }} />

          {/* Light mode only: subtle grid */}
          <div className="absolute inset-0 opacity-[0.02] dark:hidden" style={{
            backgroundImage: `linear-gradient(rgba(0,0,0,0.1) 1px, transparent 1px), linear-gradient(90deg, rgba(0,0,0,0.1) 1px, transparent 1px)`,
            backgroundSize: '64px 64px',
          }} />
        </div>

        {/* Main content area - reserve bottom space for Dock */}
        <main className="flex-1 overflow-hidden pb-20">{children}</main>
        {/* Bottom Dock */}
        <BottomDock />
      </div>
    </TooltipProvider>
  );
}
