import { useMemo, useState } from "react";
import { Link } from "@tanstack/react-router";
import { PageHeader } from "@/components/layout/page-header";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ConversionResults } from "@/components/convert/conversion-results";
import { useHistory, useHistoryDetail, useDeleteConversion } from "@/hooks/use-history";
import { useLocalHistoryStore } from "@/stores/local-history";
import { useToastStore } from "@/stores/toast";
import { useConvertBridge } from "@/stores/convert-bridge";
import { downloadAllFormatsAsZip } from "@/lib/download";
import type { HistoryListItem, ConversionResult } from "@/lib/api";
import {
  Clock,
  Trash2,
  ChevronLeft,
  Download,
  Loader2,
  Database,
  Search,
  HardDrive,
  ArrowUpDown,
  ArrowRightLeft,
} from "lucide-react";
import { motion } from "motion/react";

type SortKey = "created_at" | "workflow_name" | "coverage_percentage";

export function HistoryPage() {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedSource, setSelectedSource] = useState<"remote" | "local">("remote");
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("created_at");
  const [sortAsc, setSortAsc] = useState(false);
  const [page, setPage] = useState(0);
  const [confirmDeleteId, setConfirmDeleteId] = useState<{ id: string; source: "remote" | "local" } | null>(null);
  const pageSize = 25;

  const { data: remoteData, isLoading, error: remoteError } = useHistory();
  const detail = useHistoryDetail(selectedSource === "remote" ? selectedId : null);
  const deleteMutation = useDeleteConversion();
  const localItems = useLocalHistoryStore((s) => s.items);
  const localGet = useLocalHistoryStore((s) => s.get);
  const localRemove = useLocalHistoryStore((s) => s.remove);
  const addToast = useToastStore((s) => s.add);
  const setConvertHint = useConvertBridge((s) => s.setWorkflowName);

  const hasRemote = !remoteError && remoteData && remoteData.total > 0;

  // Merge remote + local items into a unified list
  const allItems: (HistoryListItem & { source: "remote" | "local" })[] = useMemo(() => {
    const items: (HistoryListItem & { source: "remote" | "local" })[] = [];

    if (remoteData) {
      for (const item of remoteData.items) {
        items.push({ ...item, source: "remote" });
      }
    }

    for (const item of localItems) {
      items.push({
        id: item.id,
        workflow_name: item.workflow_name,
        output_format: item.output_format,
        created_at: item.created_at,
        node_count: item.node_count,
        edge_count: item.edge_count,
        coverage_percentage: item.coverage_percentage,
        source: "local",
      });
    }

    return items;
  }, [remoteData, localItems]);

  // Filter + sort
  const filteredSorted = useMemo(() => {
    let list = allItems;
    if (search) {
      const q = search.toLowerCase();
      list = list.filter((i) => i.workflow_name.toLowerCase().includes(q));
    }
    list.sort((a, b) => {
      let cmp: number;
      if (sortKey === "workflow_name") {
        cmp = a.workflow_name.localeCompare(b.workflow_name);
      } else if (sortKey === "coverage_percentage") {
        cmp = (a.coverage_percentage ?? 0) - (b.coverage_percentage ?? 0);
      } else {
        cmp = new Date(a.created_at).getTime() - new Date(b.created_at).getTime();
      }
      return sortAsc ? cmp : -cmp;
    });
    return list;
  }, [allItems, search, sortKey, sortAsc]);

  const totalPages = Math.ceil(filteredSorted.length / pageSize);
  const paginated = filteredSorted.slice(page * pageSize, (page + 1) * pageSize);

  // Detail view
  if (selectedId) {
    let detailResult: ConversionResult | null = null;
    let detailLoading = false;

    if (selectedSource === "local") {
      const local = localGet(selectedId);
      if (local) detailResult = local.result;
    } else {
      detailResult = detail.data ?? null;
      detailLoading = detail.isLoading;
    }

    if (detailLoading) {
      return (
        <div className="flex items-center justify-center min-h-[200px]">
          <Loader2 className="h-6 w-6 animate-spin text-[var(--fg-muted)]" />
        </div>
      );
    }

    if (detailResult) {
      return (
        <div className="space-y-6">
          <PageHeader title={detailResult.workflow_name} description="Conversion detail">
            <Button variant="ghost" size="sm" onClick={() => setSelectedId(null)}>
              <ChevronLeft className="h-4 w-4" />
              Back to History
            </Button>
            <Link to="/convert" onClick={() => setConvertHint(detailResult!.workflow_name)}>
              <Button variant="ghost" size="sm">
                <ArrowRightLeft className="h-4 w-4" />
                Re-convert
              </Button>
            </Link>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => downloadAllFormatsAsZip(detailResult!.formats, detailResult!.workflow_name)}
            >
              <Download className="h-4 w-4" />
              Download All (ZIP)
            </Button>
          </PageHeader>
          <ConversionResults result={detailResult} />
        </div>
      );
    }
  }

  // List view
  return (
    <div className="space-y-6">
      <PageHeader
        title="Conversion History"
        description="Browse past conversions"
      />

      {isLoading && (
        <div className="flex items-center justify-center min-h-[200px]">
          <Loader2 className="h-6 w-6 animate-spin text-[var(--fg-muted)]" />
        </div>
      )}

      {/* Search + sort bar */}
      {allItems.length > 0 && (
        <div className="flex items-center gap-3 flex-wrap">
          <div className="relative flex-1 max-w-xs">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-[var(--fg-muted)]" />
            <input
              type="text"
              placeholder="Search workflows..."
              value={search}
              onChange={(e) => { setSearch(e.target.value); setPage(0); }}
              className="w-full pl-9 pr-3 py-1.5 rounded-lg border border-[var(--border)] bg-[var(--bg)] text-sm text-[var(--fg)] placeholder:text-[var(--fg-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--ring)]"
              aria-label="Search conversion history"
            />
          </div>
          <div className="flex items-center gap-1 text-xs text-[var(--fg-muted)]">
            <ArrowUpDown className="h-3.5 w-3.5" />
            Sort:
            {(["created_at", "workflow_name", "coverage_percentage"] as const).map((k) => (
              <button
                key={k}
                onClick={() => {
                  if (sortKey === k) setSortAsc(!sortAsc);
                  else { setSortKey(k); setSortAsc(false); }
                }}
                className={`px-2 py-0.5 rounded text-xs ${
                  sortKey === k ? "bg-[var(--ring)]/10 text-[var(--ring)] font-medium" : "hover:bg-[var(--bg-sidebar)]"
                }`}
              >
                {k === "created_at" ? "Date" : k === "workflow_name" ? "Name" : "Coverage"}
              </button>
            ))}
          </div>
          <span className="text-xs text-[var(--fg-muted)]">
            {filteredSorted.length} results
          </span>
        </div>
      )}

      {allItems.length === 0 && !isLoading && (
        <Card className="flex flex-col items-center justify-center py-12 text-center">
          <Database className="h-10 w-10 text-[var(--fg-muted)] mb-3" />
          <p className="text-sm font-medium text-[var(--fg)]">No conversions yet</p>
          <p className="text-sm text-[var(--fg-muted)] mt-1 max-w-md">
            Conversions will appear here automatically. Recent conversions are saved in your browser.
            {!hasRemote && " For persistent storage, configure the A2D_DATABASE_URL environment variable."}
          </p>
        </Card>
      )}

      {paginated.length > 0 && (
        <div className="rounded-xl border border-[var(--border)] overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-[var(--bg-sidebar)] border-b border-[var(--border)]">
                <th scope="col" className="text-left px-4 py-3 font-medium text-[var(--fg-muted)]">
                  Workflow
                </th>
                <th scope="col" className="text-left px-4 py-3 font-medium text-[var(--fg-muted)]">
                  Format
                </th>
                <th scope="col" className="text-left px-4 py-3 font-medium text-[var(--fg-muted)]">
                  Date
                </th>
                <th scope="col" className="text-right px-4 py-3 font-medium text-[var(--fg-muted)]">
                  Nodes
                </th>
                <th scope="col" className="text-right px-4 py-3 font-medium text-[var(--fg-muted)]">
                  Coverage
                </th>
                <th scope="col" className="text-center px-4 py-3 font-medium text-[var(--fg-muted)]">
                  Source
                </th>
                <th scope="col" className="text-right px-4 py-3 font-medium text-[var(--fg-muted)]">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody>
              {paginated.map((item, i) => (
                <motion.tr
                  key={`${item.source}-${item.id}`}
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ delay: Math.min(i * 0.02, 0.3) }}
                  role="button"
                  tabIndex={0}
                  aria-label={`View ${item.workflow_name} conversion`}
                  className="border-b border-[var(--border)] last:border-b-0 cursor-pointer hover:bg-[var(--bg-sidebar)]/50 transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--ring)]"
                  onClick={() => {
                    setSelectedId(item.id);
                    setSelectedSource(item.source);
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      setSelectedId(item.id);
                      setSelectedSource(item.source);
                    }
                  }}
                >
                  <td className="px-4 py-3 font-medium text-[var(--fg)]">
                    {item.workflow_name}
                  </td>
                  <td className="px-4 py-3">
                    <Badge variant="secondary">
                      {item.output_format === "multi" || !item.output_format
                        ? "all formats"
                        : item.output_format}
                    </Badge>
                  </td>
                  <td className="px-4 py-3 text-[var(--fg-muted)]">
                    <div className="flex items-center gap-1.5">
                      <Clock className="h-3.5 w-3.5" />
                      {new Date(item.created_at).toLocaleDateString(undefined, {
                        year: "numeric",
                        month: "short",
                        day: "numeric",
                      })}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-right text-[var(--fg-muted)]">
                    {item.node_count}
                  </td>
                  <td className="px-4 py-3 text-right text-[var(--fg)]">
                    {item.coverage_percentage != null
                      ? `${item.coverage_percentage.toFixed(1)}%`
                      : "\u2014"}
                  </td>
                  <td className="px-4 py-3 text-center">
                    {item.source === "local" ? (
                      <span title="Browser storage"><HardDrive className="h-3.5 w-3.5 text-[var(--fg-muted)] mx-auto" /></span>
                    ) : (
                      <span title="Database"><Database className="h-3.5 w-3.5 text-[var(--fg-muted)] mx-auto" /></span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-label="Delete conversion"
                      onClick={(e) => {
                        e.stopPropagation();
                        setConfirmDeleteId({ id: item.id, source: item.source });
                      }}
                    >
                      <Trash2 className="h-4 w-4 text-destructive" />
                    </Button>
                  </td>
                </motion.tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Delete confirmation dialog */}
      {confirmDeleteId && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
          onClick={() => setConfirmDeleteId(null)}
          onKeyDown={(e) => { if (e.key === "Escape") setConfirmDeleteId(null); }}
          role="presentation"
        >
          <div
            role="alertdialog"
            aria-labelledby="delete-dialog-title"
            aria-describedby="delete-dialog-desc"
            className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-6 shadow-xl max-w-sm mx-4"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 id="delete-dialog-title" className="text-sm font-semibold text-[var(--fg)] mb-2">Delete conversion?</h3>
            <p id="delete-dialog-desc" className="text-sm text-[var(--fg-muted)] mb-4">
              This action cannot be undone. The conversion record will be permanently removed.
            </p>
            <div className="flex justify-end gap-2">
              <Button variant="ghost" size="sm" onClick={() => setConfirmDeleteId(null)}>
                Cancel
              </Button>
              <Button
                variant="destructive"
                size="sm"
                onClick={() => {
                  if (confirmDeleteId.source === "local") {
                    localRemove(confirmDeleteId.id);
                    addToast("Conversion removed", "info");
                  } else {
                    deleteMutation.mutate(confirmDeleteId.id);
                    addToast("Conversion deleted", "info");
                  }
                  setConfirmDeleteId(null);
                }}
              >
                Delete
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            disabled={page === 0}
            onClick={() => setPage(page - 1)}
          >
            Previous
          </Button>
          <span className="text-xs text-[var(--fg-muted)]">
            Page {page + 1} of {totalPages}
          </span>
          <Button
            variant="ghost"
            size="sm"
            disabled={page >= totalPages - 1}
            onClick={() => setPage(page + 1)}
          >
            Next
          </Button>
        </div>
      )}
    </div>
  );
}
