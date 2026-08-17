function isTextItem(item: unknown): item is { str: string } {
  return (
    typeof item === "object" &&
    item !== null &&
    "str" in item &&
    typeof (item as { str: unknown }).str === "string"
  );
}

// Not a static top-level import: pdfjs-dist is the single heaviest dependency
// in this app (its own worker bundle alone is >1MB) and every user who
// hasn't touched a PDF yet — which is most of a session spent on Bank
// statements/Budget/Goals — was paying for it in the initial page load
// regardless. TabbedPanel mounts every tab's component immediately on
// first render (just toggles `hidden` via CSS, not a conditional mount —
// deliberate, so in-progress form state survives a tab switch), so a
// React.lazy() on PDFParser/PayslipHistoryUpload themselves wouldn't have
// deferred anything either; the load has to be deferred at the actual
// import() call, inside this function, triggered only by a real file
// selection. Both pdfjs-dist's own module and its worker script only
// fetch on that first real PDF upload, cached by the browser for any
// subsequent one this session.
let pdfjsLibPromise: ReturnType<typeof loadPdfjs> | null = null;

async function loadPdfjs() {
  const pdfjsLib = await import("pdfjs-dist");
  // Vite's `?url` suffix resolves this to a fingerprinted asset URL rather
  // than bundling the worker's code inline — pdf.js needs to load it as a
  // real worker script, not as parsed JS bundled with the app.
  const { default: pdfWorkerUrl } = await import("pdfjs-dist/build/pdf.worker.min.mjs?url");
  pdfjsLib.GlobalWorkerOptions.workerSrc = pdfWorkerUrl;
  return pdfjsLib;
}

/**
 * Extracts all text from a PDF entirely in the browser — the file itself
 * never leaves the device. Shared by PDFParser.tsx (single, reviewed
 * upload) and PayslipHistoryUpload.tsx (bulk, save-without-review) so the
 * extraction logic exists in exactly one place.
 */
export async function extractPdfText(file: File): Promise<string> {
  pdfjsLibPromise ??= loadPdfjs();
  const pdfjsLib = await pdfjsLibPromise;
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
