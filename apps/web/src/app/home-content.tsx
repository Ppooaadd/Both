"use client";

import Link from "next/link";
import { AudioLinesIcon, FileMusicIcon, SlidersHorizontalIcon } from "lucide-react";

import { UploadPanel } from "@/components/upload/UploadPanel";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useMe } from "@/lib/api/queries";

const STEPS = [
  { icon: AudioLinesIcon, title: "분석", text: "보컬·드럼·베이스를 분리하고 템포, 박자, 조성, 코드, 멜로디를 찾습니다." },
  { icon: SlidersHorizontalIcon, title: "편곡", text: "초급·중급·고급 규칙에 맞춰 두 손 피아노 편곡을 만들고, 설정을 바꿔 몇 초 만에 다시 만듭니다." },
  { icon: FileMusicIcon, title: "내보내기", text: "PDF 악보, MusicXML, MIDI, 피아노 연주 MP3·WAV를 내려받습니다." },
];

export function HomeContent() {
  const me = useMe();
  return (
    <div className="grid gap-10 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)] lg:items-start">
      <section className="flex flex-col gap-6 lg:sticky lg:top-24">
        <div className="flex flex-col gap-3">
          <p className="font-mono text-xs tracking-wide text-brass">MP3 · WAV · M4A → 피아노 악보</p>
          <h1 className="text-3xl font-bold leading-tight tracking-tight sm:text-4xl">
            좋아하는 곡을 내 실력에 맞는 피아노 악보로
          </h1>
          <p className="max-w-prose text-muted-foreground">
            음원을 올리면 분석부터 편곡, 악보와 연주 음원까지 한 번에 만듭니다. 결과는 피아노 롤과 악보로 바로 확인하고
            들어볼 수 있습니다.
          </p>
        </div>
        <ol className="grid gap-3">
          {STEPS.map((s, i) => (
            <li key={s.title} className="flex gap-3">
              <span className="grid size-8 shrink-0 place-items-center rounded-md bg-secondary text-secondary-foreground">
                <s.icon className="size-4" />
              </span>
              <div>
                <p className="font-medium">
                  {i + 1}. {s.title}
                </p>
                <p className="text-sm text-muted-foreground">{s.text}</p>
              </div>
            </li>
          ))}
        </ol>
        <p className="text-xs text-muted-foreground">
          업로드한 원본 음원은 7일 뒤 자동 삭제됩니다. 저작권이 있는 곡은 개인 연습 용도로만 사용해 주세요.
        </p>
      </section>

      <Card>
        <CardContent>
          {me.isPending ? (
            <Skeleton className="h-72 w-full" />
          ) : me.data ? (
            <UploadPanel />
          ) : (
            <div className="flex flex-col items-center gap-4 py-12 text-center">
              <p className="text-lg font-medium">로그인하고 첫 곡을 올려 보세요</p>
              <p className="text-sm text-muted-foreground">무료 플랜: 매달 60분 분량 분석, 곡당 최대 10분</p>
              <div className="flex gap-2">
                <Button asChild>
                  <Link href="/signup">가입하기</Link>
                </Button>
                <Button asChild variant="outline">
                  <Link href="/login">로그인</Link>
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
