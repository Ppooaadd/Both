import type { Metadata } from "next";
import { Suspense } from "react";

import { AuthForm } from "@/components/auth/AuthForm";

export const metadata: Metadata = { title: "로그인" };

export default function LoginPage() {
  return (
    <div className="flex justify-center pt-8">
      <Suspense>
        <AuthForm mode="login" />
      </Suspense>
    </div>
  );
}
