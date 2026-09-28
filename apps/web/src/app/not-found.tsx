import Link from "next/link";

import { Button } from "@/components/ui/button";

export default function NotFound() {
  return (
    <div className="flex flex-col items-center gap-4 py-24 text-center">
      <p className="font-mono text-sm text-brass">404</p>
      <h1 className="text-2xl font-semibold">페이지를 찾을 수 없습니다</h1>
      <p className="text-muted-foreground">주소가 바뀌었거나 삭제된 프로젝트일 수 있습니다.</p>
      <Button asChild>
        <Link href="/projects">내 프로젝트로</Link>
      </Button>
    </div>
  );
}
