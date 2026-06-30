import { Badge } from "@/components/ui/badge";
import { CheckCircle, AlertTriangle, XCircle } from "lucide-react";

interface StatusBadgeProps {
  success: boolean;
  hasWarnings?: boolean;
}

export function StatusBadge({ success, hasWarnings }: StatusBadgeProps) {
  if (!success) {
    return (
      <Badge variant="destructive" className="gap-1">
        <XCircle className="h-3 w-3" /> Failed
      </Badge>
    );
  }
  if (hasWarnings) {
    return (
      <Badge variant="warning" className="gap-1">
        <AlertTriangle className="h-3 w-3" /> Partial
      </Badge>
    );
  }
  return (
    <Badge variant="success" className="gap-1">
      <CheckCircle className="h-3 w-3" /> OK
    </Badge>
  );
}
