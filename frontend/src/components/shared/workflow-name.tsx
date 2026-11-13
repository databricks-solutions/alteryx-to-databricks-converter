import { Badge } from "@/components/ui/badge";
import { isMacroFile } from "@/lib/api";

/** A workflow's name, marked when it's a macro the other workflows can call. */
export function WorkflowName({ fileName }: { fileName: string }) {
  if (!isMacroFile(fileName)) return <>{fileName}</>;
  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      {fileName}
      <Badge variant="secondary" title="A macro. Workflows in this project that call it use this file.">
        macro
      </Badge>
    </span>
  );
}
