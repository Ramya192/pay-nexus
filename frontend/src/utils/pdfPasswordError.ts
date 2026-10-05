/**
 * Thrown by extractPdfText when a PDF is encrypted and no password (or the
 * wrong one) was supplied. Lives in its own module rather than pdfText.ts so
 * components can `instanceof` it without importing pdfText.ts — the uploader
 * tests mock that whole module.
 */
export class PdfPasswordError extends Error {
  constructor(readonly incorrect: boolean) {
    super(incorrect ? "Incorrect PDF password." : "This PDF is password-protected.");
    this.name = "PdfPasswordError";
  }
}
