import type { Metadata } from "next";

import { RequireAuth } from "@/components/auth/RequireAuth";
import { ProjectList } from "@/components/project/ProjectList";

export const metadata: Metadata = { title: "내 프로젝트" };

export default function ProjectsPage() {
  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-2xl font-semibold tracking-tight">내 프로젝트</h1>
      <RequireAuth>
        <ProjectList />
      </RequireAuth>
    </div>
  );
}
