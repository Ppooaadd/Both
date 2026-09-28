"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { Loader2Icon } from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { errorMessage } from "@/lib/api/client";
import { useLogin, useSignup } from "@/lib/api/queries";

/** Only allow in-app relative redirects (no open redirect via ?next=). */
export function safeNext(next: string | null): string {
  return next && next.startsWith("/") && !next.startsWith("//") ? next : "/";
}

export function passwordProblem(pw: string): string | null {
  if (pw.length < 10) return "비밀번호는 10자 이상이어야 합니다.";
  const kinds = [/[a-z]/, /[A-Z]/, /\d/, /[^\w\s]/].filter((r) => r.test(pw)).length;
  if (kinds < 2) return "영문 대/소문자, 숫자, 특수문자 중 2종류 이상을 섞어 주세요.";
  return null;
}

export function AuthForm({ mode }: { mode: "login" | "signup" }) {
  const router = useRouter();
  const search = useSearchParams();
  const login = useLogin();
  const signup = useSignup();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);
  const mutation = mode === "login" ? login : signup;
  const next = safeNext(search.get("next"));

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setLocalError(null);
    if (mode === "signup") {
      const problem = passwordProblem(password);
      if (problem) {
        setLocalError(problem);
        return;
      }
      signup.mutate({ email, password, display_name: name.trim() || email.split("@")[0] }, { onSuccess: () => router.push(next) });
    } else {
      login.mutate({ email, password }, { onSuccess: () => router.push(next) });
    }
  };

  const error = localError ?? (mutation.error ? errorMessage(mutation.error) : null);

  return (
    <Card className="w-full max-w-sm">
      <CardHeader>
        <CardTitle className="text-lg">{mode === "login" ? "로그인" : "계정 만들기"}</CardTitle>
        <CardDescription>
          {mode === "login" ? "업로드한 곡과 편곡을 이어서 작업합니다." : "무료 플랜은 매달 60분 분량의 음원을 분석할 수 있습니다."}
        </CardDescription>
      </CardHeader>
      <form onSubmit={onSubmit} noValidate>
        <CardContent className="flex flex-col gap-4">
          {mode === "signup" && (
            <div className="grid gap-2">
              <Label htmlFor="name">이름</Label>
              <Input id="name" autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} maxLength={80} />
            </div>
          )}
          <div className="grid gap-2">
            <Label htmlFor="email">이메일</Label>
            <Input id="email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="password">비밀번호</Label>
            <Input
              id="password"
              type="password"
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              aria-describedby={mode === "signup" ? "password-hint" : undefined}
            />
            {mode === "signup" && (
              <p id="password-hint" className="text-xs text-muted-foreground">
                10자 이상, 문자 종류 2가지 이상
              </p>
            )}
          </div>
          {error && (
            <Alert variant="destructive">
              <AlertDescription className="text-destructive">{error}</AlertDescription>
            </Alert>
          )}
        </CardContent>
        <CardFooter className="mt-5 flex-col items-stretch gap-3">
          <Button type="submit" disabled={mutation.isPending || !email || !password}>
            {mutation.isPending && <Loader2Icon className="animate-spin" />}
            {mode === "login" ? "로그인" : "가입하기"}
          </Button>
          <p className="text-center text-sm text-muted-foreground">
            {mode === "login" ? (
              <>
                계정이 없나요?{" "}
                <Link className="text-primary underline-offset-4 hover:underline" href={`/signup?next=${encodeURIComponent(next)}`}>
                  가입하기
                </Link>
              </>
            ) : (
              <>
                이미 계정이 있나요?{" "}
                <Link className="text-primary underline-offset-4 hover:underline" href={`/login?next=${encodeURIComponent(next)}`}>
                  로그인
                </Link>
              </>
            )}
          </p>
        </CardFooter>
      </form>
    </Card>
  );
}
