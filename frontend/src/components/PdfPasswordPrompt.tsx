import { useState, type FormEvent } from "react";

/**
 * Asks for the password of an encrypted PDF (bank statements are very often
 * password-protected). The password is only handed to `onSubmit`, which passes
 * it to pdf.js in the browser — it never reaches the server. `incorrect` is
 * true when the previous attempt was rejected.
 */
export function PdfPasswordPrompt({
  fileName,
  incorrect,
  disabled,
  onSubmit,
  onCancel,
}: {
  fileName: string;
  incorrect: boolean;
  disabled?: boolean;
  onSubmit: (password: string) => void;
  onCancel: () => void;
}) {
  const [password, setPassword] = useState("");

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (password) onSubmit(password);
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-1.5">
      <label className="block text-xs font-medium text-slate-600" htmlFor="pdf-password">
        {fileName} is password-protected — enter its password
      </label>
      <div className="flex items-center gap-2">
        <input
          id="pdf-password"
          type="password"
          autoComplete="off"
          autoFocus
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          disabled={disabled}
          className="min-w-0 flex-1 rounded-md border border-slate-300 px-2.5 py-1.5 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
        />
        <button
          type="submit"
          disabled={disabled || !password}
          className="shrink-0 rounded-md bg-brand-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
        >
          Unlock
        </button>
        <button
          type="button"
          onClick={onCancel}
          disabled={disabled}
          className="shrink-0 rounded-md px-2 py-1.5 text-sm text-slate-500 hover:text-slate-700 disabled:opacity-50"
        >
          Cancel
        </button>
      </div>
      {incorrect && <p className="text-xs text-red-600">That password didn't work — try again.</p>}
    </form>
  );
}
