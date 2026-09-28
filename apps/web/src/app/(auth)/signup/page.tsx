import type { Metadata } from "next";
import { Suspense } from "react";

import { AuthForm } from "@/components/auth/AuthForm";

export const metadata: Metadata = { title: "가입하기" };

export default function SignupPage() {
  return (
    <div className="flex justify-center pt-8">
      <Suspense>
        <AuthForm mode="signup" />
      </Suspense>
    </div>
  );
}
