import * as pdfjsLib from "pdfjs-dist";
// Vite's `?url` suffix resolves this to a fingerprinted asset URL rather than
// bundling the worker's code inline — pdf.js needs to load it as a real
// worker script, not as parsed JS in the main bundle.
import pdfWorkerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";

pdfjsLib.GlobalWorkerOptions.workerSrc = pdfWorkerUrl;

function isTextItem(item: unknown): item is { str: string } {
  return (
    typeof item === "object" &&
    item !== null &&
    "str" in item &&
    typeof (item as { str: unknown }).str === "string"
  );
}

/**
 * Extracts all text from a PDF entirely in the browser — the file itself
 * never leaves the device. Shared by PDFParser.tsx (single, reviewed
 * upload) and PayslipHistoryUpload.tsx (bulk, save-without-review) so the
 * extraction logic exists in exactly one place.
 */
export async function extractPdfText(file: File): Promise<string> {
  const buffer = await file.arrayBuffer();
  const pdf = await pdfjsLib.getDocument({ data: buffer }).promise;
  let text = "";
  for (let i = 1; i <= pdf.numPages; i++) {
    const page = await pdf.getPage(i);
    const content = await page.getTextContent();
    text += content.items.map((item) => (isTextItem(item) ? item.str : "")).join(" ") + "\n";
  }
  return text;
}
