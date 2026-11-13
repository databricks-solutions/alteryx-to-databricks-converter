import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Project, type ProjectSummary, type ServerStatus } from "@/lib/api";
import { projectQueryKey } from "@/hooks/use-project-context";

/** What the server has turned on. Fixed for the server's lifetime. */
export function useServerStatus() {
  return useQuery<ServerStatus>({
    queryKey: ["status"],
    queryFn: () => api.status(),
    staleTime: Infinity,
    retry: 1,
  });
}

/** Saved projects, asked for only when the server has a database. Without one,
 * projects live in the browser and there's nothing to list. */
export function useProjects() {
  const status = useServerStatus();
  return useQuery<{ projects: ProjectSummary[]; total: number }>({
    queryKey: ["projects"],
    queryFn: () => api.listProjects(),
    retry: false,
    enabled: status.data?.projects.configured === true,
  });
}

/** True when the server has no database configured (so projects live in the
 * browser), as opposed to a configured database that isn't responding. */
export function isProjectsNotConfigured(status: ServerStatus | undefined): boolean {
  return status?.projects.configured === false;
}

function useInvalidateProject() {
  const qc = useQueryClient();
  return (id: string) => {
    qc.invalidateQueries({ queryKey: projectQueryKey(id) });
    qc.invalidateQueries({ queryKey: ["projects"] });
  };
}

export function useCreateProject() {
  const qc = useQueryClient();
  return useMutation<Project, Error, { name: string; files: File[] }>({
    mutationFn: ({ name, files }) => api.createProject(name, files),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["projects"] }),
  });
}

export function useAddWorkflows() {
  const invalidate = useInvalidateProject();
  return useMutation<Project, Error, { id: string; files: File[] }>({
    mutationFn: ({ id, files }) => api.addProjectWorkflows(id, files),
    onSuccess: (project) => invalidate(project.id),
  });
}

export function useRemoveWorkflow() {
  const invalidate = useInvalidateProject();
  return useMutation<Project, Error, { projectId: string; workflowId: string }>({
    mutationFn: ({ projectId, workflowId }) => api.removeProjectWorkflow(projectId, workflowId),
    onSuccess: (_p, { projectId }) => invalidate(projectId),
  });
}

export function useRenameProject() {
  const invalidate = useInvalidateProject();
  return useMutation<Project, Error, { id: string; name: string }>({
    mutationFn: ({ id, name }) => api.renameProject(id, name),
    onSuccess: (_p, { id }) => invalidate(id),
  });
}

export function useDeleteProject() {
  const qc = useQueryClient();
  return useMutation<{ deleted: string }, Error, { id: string }>({
    mutationFn: ({ id }) => api.deleteProject(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["projects"] }),
  });
}
