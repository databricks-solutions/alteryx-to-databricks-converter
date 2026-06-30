import JSZip from "jszip";
import { saveAs } from "file-saver";
import type { FormatResult, GeneratedFile } from "./api";

export async function downloadAsZip(
  files: GeneratedFile[],
  zipName: string,
) {
  const zip = new JSZip();
  for (const f of files) {
    zip.file(f.filename, f.content);
  }
  const blob = await zip.generateAsync({ type: "blob" });
  saveAs(blob, `${zipName}.zip`);
}

export async function downloadFormatAsZip(
  formatResult: FormatResult,
  workflowName: string,
) {
  const zip = new JSZip();
  for (const f of formatResult.files) {
    zip.file(f.filename, f.content);
  }
  const blob = await zip.generateAsync({ type: "blob" });
  saveAs(blob, `${workflowName}-${formatResult.format}.zip`);
}

export async function downloadAllFormatsAsZip(
  formats: Record<string, FormatResult>,
  workflowName: string,
) {
  const zip = new JSZip();
  for (const [formatId, fr] of Object.entries(formats)) {
    if (fr.status !== "success") continue;
    const folder = zip.folder(`${workflowName}/${formatId}`);
    if (!folder) continue;
    for (const f of fr.files) {
      folder.file(f.filename, f.content);
    }
  }
  const blob = await zip.generateAsync({ type: "blob" });
  saveAs(blob, `${workflowName}-all-formats.zip`);
}
