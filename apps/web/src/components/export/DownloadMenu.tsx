"use client";

import { DownloadIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { exportHref } from "@/lib/api/queries";
import type { Arrangement, ExportFormat } from "@/lib/api/schemas";
import { EXPORT_LABEL } from "@/lib/music";
import { formatBytes } from "@/lib/utils";

const ORDER: ExportFormat[] = ["pdf", "musicxml", "midi", "mp3", "wav"];

export function DownloadMenu({ arrangement }: { arrangement: Arrangement }) {
  const available = new Map(arrangement.exports.map((e) => [e.format, e]));
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button disabled={available.size === 0}>
          <DownloadIcon />
          다운로드
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-64">
        <DropdownMenuLabel>파일 형식 선택 (링크는 5분간 유효)</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {ORDER.map((fmt) => {
          const e = available.get(fmt);
          return (
            <DropdownMenuItem key={fmt} disabled={!e} asChild>
              {/* Same-origin link; the API redirects to a presigned attachment URL. */}
              <a href={e ? exportHref(arrangement.id, fmt) : undefined} className="flex w-full justify-between">
                <span className="grid">
                  <span className="font-medium">{EXPORT_LABEL[fmt].name}</span>
                  <span className="text-xs text-muted-foreground">{e ? EXPORT_LABEL[fmt].hint : "준비되지 않음"}</span>
                </span>
                {e && <span className="font-mono text-xs text-muted-foreground">{formatBytes(e.size_bytes)}</span>}
              </a>
            </DropdownMenuItem>
          );
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
