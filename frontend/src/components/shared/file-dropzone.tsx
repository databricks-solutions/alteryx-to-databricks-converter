import { useCallback } from "react";
import { useDropzone } from "react-dropzone";
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
  accept = ".yxmd",
}: FileDropzoneProps) {
  const onDrop = useCallback(
    (accepted: File[]) => {
      if (multiple) {
        onFilesChange([...files, ...accepted]);
      } else {
        onFilesChange(accepted.slice(0, 1));
      }
    },
    [files, onFilesChange, multiple],
  );

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { "application/xml": [accept] },
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
              ? "Tap to browse for .yxmd files"
              : "Drag & drop .yxmd files"}
        </p>
        {!isDragActive && !("ontouchstart" in (typeof window !== "undefined" ? window : {})) && (
          <p className="text-xs text-[var(--fg-muted)] mt-1">
            or click to browse
          </p>
        )}
      </div>

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
