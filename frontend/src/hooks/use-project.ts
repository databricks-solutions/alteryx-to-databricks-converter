import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, type Project, type ProjectSummary } from "@/lib/api";
import { projectQueryKey } from "@/hooks/use-project-context";

/** Saved projects. A 503 (no database on this server) surfaces as the error. */
export function useProjects() {
  return useQuery<{ projects: ProjectSummary[]; total: number }>({
    queryKey: ["projects"],
    queryFn: () => api.listProjects(),
    retry: false,
  });
}

/** True when the server has no database configured (so projects live in the
 * browser), as opposed to a configured database that isn't responding. */
export function isProjectsNotConfigured(error: Error | null): boolean {
  return error instanceof ApiError && error.status === 503 && /doesn't have one configured/i.test(error.message);
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
