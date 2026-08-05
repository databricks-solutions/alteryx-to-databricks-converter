import { saveAs } from "file-saver";

/** Download any JSON-serializable report as a formatted .json file. */
export function downloadJson(data: unknown, filename: string) {
  const blob = new Blob([JSON.stringify(data, null, 2)], {
    type: "application/json;charset=utf-8",
  });
  saveAs(blob, filename);
}
