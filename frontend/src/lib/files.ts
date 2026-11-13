import { saveAs } from "file-saver";

/** A project or workflow name made safe for a download file name. */
export function slugify(name: string, fallback = "project"): string {
  return name.replace(/[^A-Za-z0-9_-]+/g, "_").replace(/^_+|_+$/g, "") || fallback;
}

/** Download a string as a file. */
export function downloadText(filename: string, content: string, mime = "text/plain;charset=utf-8") {
  saveAs(new Blob([content], { type: mime }), filename);
}
