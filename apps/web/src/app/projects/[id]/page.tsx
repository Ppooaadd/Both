import { RequireAuth } from "@/components/auth/RequireAuth";
import { ProjectWorkspace } from "@/components/project/ProjectWorkspace";

export default async function ProjectPage(props: PageProps<"/projects/[id]">) {
  const { id } = await props.params;
  return (
    <RequireAuth>
      <ProjectWorkspace projectId={id} />
    </RequireAuth>
  );
}
