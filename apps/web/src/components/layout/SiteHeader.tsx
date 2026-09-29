"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { FolderIcon, LogOutIcon, MusicIcon, PlusIcon, UserIcon } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { AUTH_EXPIRED_EVENT } from "@/lib/api/client";
import { qk, useLogout, useMe } from "@/lib/api/queries";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/", label: "새 편곡", icon: PlusIcon },
  { href: "/projects", label: "내 프로젝트", icon: FolderIcon },
];

export function SiteHeader() {
  const pathname = usePathname();
  const router = useRouter();
  const qc = useQueryClient();
  const me = useMe();
  const logout = useLogout();

  useEffect(() => {
    const onExpired = () => {
      qc.setQueryData(qk.me, null);
      toast.info("로그인이 만료되었습니다. 다시 로그인해 주세요.");
      router.push(`/login?next=${encodeURIComponent(window.location.pathname)}`);
    };
    window.addEventListener(AUTH_EXPIRED_EVENT, onExpired);
    return () => window.removeEventListener(AUTH_EXPIRED_EVENT, onExpired);
  }, [qc, router]);

  return (
    <header className="galaxy-glass-panel sticky top-0 z-40 rounded-none border-x-0 border-t-0 border-b bg-background/60">
      <div className="mx-auto flex h-14 max-w-6xl items-center gap-3 px-4 sm:gap-6">
        <Link href="/" className="flex items-center gap-2 font-semibold tracking-tight">
          <span className="grid size-7 place-items-center rounded-md bg-primary text-primary-foreground">
            <MusicIcon className="size-4" />
          </span>
          <span className="hidden sm:inline">PianoForge</span>
        </Link>
        {me.data && (
          <nav className="flex items-center gap-1 text-sm" aria-label="주 메뉴">
            {NAV.map((item) => {
              const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  aria-label={item.label}
                  className={cn(
                    "flex items-center gap-1.5 rounded-md px-2.5 py-1.5 whitespace-nowrap text-muted-foreground transition-colors hover:text-foreground sm:px-3",
                    active && "bg-secondary text-foreground",
                  )}
                >
                  <item.icon className="size-4 sm:hidden" />
                  <span className="hidden sm:inline">{item.label}</span>
                </Link>
              );
            })}
          </nav>
        )}
        <div className="ml-auto">
          {me.data ? (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="sm" className="gap-2" aria-label="계정 메뉴">
                  <UserIcon />
                  <span className="hidden max-w-[140px] truncate sm:inline">{me.data.display_name}</span>
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuLabel>{me.data.email}</DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  onSelect={() =>
                    logout.mutate(undefined, {
                      onSettled: () => router.push("/login"),
                    })
                  }
                >
                  <LogOutIcon />
                  로그아웃
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          ) : me.isPending ? null : (
            <div className="flex gap-2">
              <Button asChild variant="ghost" size="sm">
                <Link href="/login">로그인</Link>
              </Button>
              <Button asChild size="sm">
                <Link href="/signup">가입하기</Link>
              </Button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
