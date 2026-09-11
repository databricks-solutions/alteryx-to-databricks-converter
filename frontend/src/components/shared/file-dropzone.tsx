import { useCallback, useState } from "react";
import { useDropzone, type FileRejection } from "react-dropzone";
import { Upload, X } from "lucide-react";
import { motion, AnimatePresence } from "motion/react";
import { cn } from "@/lib/cn";
import { Button } from "@/components/ui/button";

interface FileDropzoneProps {
  files: File[];
  onFilesChange: (files: File[]) => void;
  multiple?: boolean;
  accept?: string;
}

export function FileDropzone({
  files,
  onFilesChange,
  multiple = false,
  accept = ".yxmd,.yxmc,.yxwz,.yxzp",
}: FileDropzoneProps) {
  const [notice, setNotice] = useState<string | null>(null);

  const fileKey = (f: File) => `${f.name}-${f.size}-${f.lastModified}`;

  const onDrop = useCallback(
    (accepted: File[], rejections: FileRejection[]) => {
      const messages: string[] = [];
      if (rejections.length > 0) {
        const names = rejections.map((r) => r.file.name).join(", ");
        messages.push(`Skipped (unsupported type or too large): ${names}`);
      }
      if (multiple) {
        const existing = new Set(files.map(fileKey));
        const deduped: File[] = [];
        let dupes = 0;
        for (const f of accepted) {
          if (existing.has(fileKey(f))) {
            dupes += 1;
          } else {
            existing.add(fileKey(f));
            deduped.push(f);
          }
        }
        if (dupes > 0) messages.push(`${dupes} duplicate file${dupes === 1 ? "" : "s"} skipped.`);
        if (deduped.length > 0) onFilesChange([...files, ...deduped]);
      } else if (accepted.length > 0) {
        onFilesChange(accepted.slice(0, 1));
      }
      setNotice(messages.length > 0 ? messages.join(" ") : null);
    },
    [files, onFilesChange, multiple],
  );

  // react-dropzone wants MIME type -> extension list. Alteryx workflows/macros/
  // apps are XML; a .yxzp package is a ZIP. Group each extension under the right
  // MIME so both the browse dialog and drag-drop admit them.
  const acceptMap = accept
    .split(",")
    .map((ext) => ext.trim())
    .filter(Boolean)
    .reduce<Record<string, string[]>>((map, ext) => {
      const mime = ext.toLowerCase() === ".yxzp" ? "application/zip" : "application/xml";
      (map[mime] ??= []).push(ext);
      return map;
    }, {});

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: acceptMap,
    multiple,
  });

  const removeFile = (file: File) => {
    onFilesChange(files.filter((f) => f !== file));
  };

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  return (
    <div className="space-y-3">
      <div
        {...getRootProps()}
        role="button"
        aria-label="Upload workflow files — drag and drop or click to browse"
        className={cn(
          "flex flex-col items-center justify-center rounded-xl border-2 border-dashed p-8 transition-colors cursor-pointer",
          isDragActive
            ? "border-[var(--ring)] bg-[var(--ring)]/5"
            : "border-[var(--border)] hover:border-[var(--fg-muted)]",
        )}
      >
        <input {...getInputProps()} />
        <motion.div
          animate={{ scale: isDragActive ? 1.1 : 1 }}
          transition={{ type: "spring", stiffness: 300, damping: 20 }}
        >
          <Upload className="h-8 w-8 text-[var(--fg-muted)] mb-3" />
        </motion.div>
        <p className="text-sm font-medium text-[var(--fg)]">
          {isDragActive
            ? "Drop files here"
            : typeof window !== "undefined" && ("ontouchstart" in window || window.matchMedia("(pointer: coarse)").matches)
              ? "Tap to browse for Alteryx files"
              : "Drag & drop Alteryx files"}
        </p>
        {!isDragActive && !("ontouchstart" in (typeof window !== "undefined" ? window : {})) && (
          <p className="text-xs text-[var(--fg-muted)] mt-1">
            or click to browse
          </p>
        )}
      </div>

      {notice && (
        <p role="status" className="text-xs text-amber-500">
          {notice}
        </p>
      )}

      {/* File list */}
      <AnimatePresence>
        {files.map((file) => (
          <motion.div
            key={`${file.name}-${file.size}-${file.lastModified}`}
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="flex items-center justify-between rounded-lg border border-[var(--border)] bg-[var(--bg-card)] px-4 py-2"
          >
            <span className="text-sm text-[var(--fg)] truncate">
              {file.name}
              <span className="ml-2 text-xs text-[var(--fg-muted)]">({formatSize(file.size)})</span>
            </span>
            <Button
              variant="ghost"
              size="icon"
              aria-label={`Remove ${file.name}`}
              onClick={() => removeFile(file)}
              className="h-6 w-6 shrink-0"
            >
              <X className="h-3 w-3" />
            </Button>
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}
