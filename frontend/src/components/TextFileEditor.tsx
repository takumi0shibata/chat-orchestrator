import { useEffect, useRef, useState } from "react";
import { Download, RefreshCw, Save, X } from "lucide-react";
import { api } from "../api";

interface TextDocument {
  path: string;
  content: string;
  revision: string;
  size: number;
}

export function TextFileEditor({ conversationId, path, onClose, onSaved }: {
  conversationId: string;
  path: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const editor = useRef<HTMLTextAreaElement>(null);
  const [document, setDocument] = useState<TextDocument | null>(null);
  const [content, setContent] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [reload, setReload] = useState(0);
  const pendingSave = useRef(false);
  const dirty = document !== null && content !== document.content;
  const endpoint = `/conversations/${conversationId}/file?path=${encodeURIComponent(path)}`;

  useEffect(() => {
    const element = dialog.current!;
    const previousFocus = window.document.activeElement as HTMLElement | null;
    element.showModal();
    return () => {
      element.close();
      previousFocus?.focus();
    };
  }, []);

  useEffect(() => {
    const abort = new AbortController();
    setLoading(true);
    setError("");
    setSaved(false);
    api<TextDocument>(endpoint, { signal: abort.signal }).then((next) => {
      if (abort.signal.aborted) return;
      setDocument(next);
      setContent(next.content);
    }).catch((cause) => {
      if (!abort.signal.aborted) setError(cause instanceof Error ? cause.message : String(cause));
    }).finally(() => {
      if (!abort.signal.aborted) setLoading(false);
    });
    return () => abort.abort();
  }, [endpoint, reload]);

  useEffect(() => {
    if (!dirty && !saving) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty, saving]);

  useEffect(() => {
    if (!loading && document) editor.current?.focus();
  }, [loading, document]);

  function close() {
    if (pendingSave.current) return;
    if (dirty && !window.confirm("Discard unsaved changes to this file?")) return;
    onClose();
  }

  async function save() {
    if (!document || !dirty || loading || pendingSave.current) return;
    pendingSave.current = true;
    setSaving(true);
    setError("");
    setSaved(false);
    try {
      const next = await api<TextDocument>(endpoint, {
        method: "PUT",
        body: JSON.stringify({ content, revision: document.revision }),
      });
      setDocument(next);
      setContent(next.content);
      setSaved(true);
      onSaved();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      pendingSave.current = false;
      setSaving(false);
    }
  }

  return (
    <dialog ref={dialog} className="text-editor-dialog" aria-labelledby="text-editor-title"
      onCancel={(event) => { event.preventDefault(); close(); }}
      onKeyDown={(event) => {
        if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") {
          event.preventDefault();
          void save();
        }
      }}>
      <header className="text-editor-header">
        <div className="text-editor-heading">
          <h2 id="text-editor-title">{path.split("/").pop()}</h2>
          <p title={path}>{path}</p>
        </div>
        <button type="button" className="text-editor-close" aria-label="Close file editor" disabled={saving} onClick={close}><X size={19} /></button>
      </header>
      <div className="text-editor-toolbar">
        <span role="status">{loading ? "Loading…" : saving ? "Saving…" : dirty ? "Unsaved changes" : saved ? "Saved" : document ? "UTF-8" : "Text editor"}</span>
        <a href={`/api/conversations/${conversationId}/download?path=${encodeURIComponent(path)}`} download title="Download original file"><Download size={15} /><span>Download</span></a>
        <button type="button" disabled={loading || saving} onClick={() => {
          if (dirty && !window.confirm("Discard your edits and reload this file from disk?")) return;
          setReload((value) => value + 1);
        }}><RefreshCw size={15} /><span>Reload</span></button>
        <button type="button" className="text-editor-save" disabled={!dirty || loading || saving} title="Save (⌘/Ctrl+S)" onClick={() => void save()}><Save size={15} /><span>Save</span></button>
      </div>
      {error && <p className="text-editor-error" role="alert">{error}</p>}
      {document && <textarea ref={editor} className="text-editor-input" aria-label="File content" value={content}
        readOnly={loading || saving} spellCheck={false} autoCapitalize="off" autoCorrect="off" wrap="off"
        onChange={(event) => { setContent(event.target.value); setSaved(false); }} />}
      {!document && <div className="text-editor-empty">{loading ? "Opening file…" : "Text editing is available for Markdown, plain text, configuration, and source files up to 1 MiB."}</div>}
      <footer className="text-editor-footer">{document ? "Save updates the original file in your project." : "You can download this file to open it in another app."}</footer>
    </dialog>
  );
}
