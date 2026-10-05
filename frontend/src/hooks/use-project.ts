import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Project, type ProjectSummary } from "@/lib/api";
import { useProjectStore } from "@/stores/project";

/** List saved projects. `enabled` lets a caller skip the call when projects are
 * known to be unavailable (no backend). A 503 surfaces as the query error. */
export function useProjects(enabled = true) {
  return useQuery<{ projects: ProjectSummary[]; total: number }>({
    queryKey: ["projects"],
    queryFn: () => api.listProjects(),
    enabled,
    retry: false,
  });
}

/** The active project (fetched by the persisted id), or null when none is set. */
export function useActiveProject() {
  const activeId = useProjectStore((s) => s.activeProjectId);
  return useQuery<Project | null>({
    queryKey: ["project", activeId],
    queryFn: () => (activeId ? api.getProject(activeId) : Promise.resolve(null)),
    enabled: activeId != null,
    retry: false,
  });
}

export function useCreateProject() {
  const qc = useQueryClient();
  const setActive = useProjectStore((s) => s.setActiveProject);
  return useMutation<Project, Error, { name: string; files: File[] }>({
    mutationFn: ({ name, files }) => api.createProject(name, files),
    onSuccess: (project) => {
      setActive(project.id);
      qc.invalidateQueries({ queryKey: ["projects"] });
    },
  });
}

export function useAddWorkflows() {
  const qc = useQueryClient();
  return useMutation<Project, Error, { id: string; files: File[] }>({
    mutationFn: ({ id, files }) => api.addProjectWorkflows(id, files),
    onSuccess: (project) => {
      qc.invalidateQueries({ queryKey: ["project", project.id] });
      qc.invalidateQueries({ queryKey: ["projects"] });
    },
  });
}

/** Run analysis over the project's stored estate (no re-upload), advancing its
 * workflows to "assessed". Refetches the project so the journey rail updates. */
export function useAssessProject() {
  const qc = useQueryClient();
  return useMutation<unknown, Error, { projectId: string }>({
    mutationFn: ({ projectId }) => api.analyze([], projectId),
    onSuccess: (_data, { projectId }) => {
      qc.invalidateQueries({ queryKey: ["project", projectId] });
      qc.invalidateQueries({ queryKey: ["projects"] });
    },
  });
}
