import { useEffect, useState } from "react";
import "./research-workbench.css";

export type AnnotationTargetType = "post" | "stimulus" | "soliloquy";

export type ResearchAnnotation = {
  schema_version: string;
  annotation_id: string;
  run_id: string;
  target_type: AnnotationTargetType;
  target_event_id: string;
  note: string;
  tags: string[];
  bookmarked: boolean;
  created_at: string;
  updated_at: string;
};

export type AnnotationTarget = {
  type: AnnotationTargetType;
  eventId: string;
  label: string;
  preview: string;
  annotation?: ResearchAnnotation;
};

async function payload(response: Response): Promise<unknown> {
  try {
    return await response.json() as unknown;
  } catch {
    return null;
  }
}

function message(value: unknown, fallback: string) {
  if (typeof value === "object" && value !== null && "detail" in value) {
    return String((value as { detail: unknown }).detail);
  }
  return fallback;
}

function AnnotationEditorDialog({
  runId,
  target,
  onClose,
  onSaved,
  onDeleted,
}: {
  runId: string;
  target: AnnotationTarget;
  onClose: () => void;
  onSaved: (annotation: ResearchAnnotation) => void;
  onDeleted: (annotationId: string) => void;
}) {
  const [note, setNote] = useState(target.annotation?.note ?? "");
  const [tags, setTags] = useState(target.annotation?.tags.join(", ") ?? "");
  const [bookmarked, setBookmarked] = useState(target.annotation?.bookmarked ?? true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);

  const parsedTags = tags
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);

  const save = async () => {
    setSaving(true);
    setError("");
    const existing = target.annotation;
    const endpoint = existing
      ? `/api/runs/${encodeURIComponent(runId)}/annotations/${encodeURIComponent(existing.annotation_id)}`
      : `/api/runs/${encodeURIComponent(runId)}/annotations`;
    const body = existing
      ? { note, tags: parsedTags, bookmarked }
      : {
          target_type: target.type,
          target_event_id: target.eventId,
          note,
          tags: parsedTags,
          bookmarked,
        };
    try {
      const response = await fetch(endpoint, {
        method: existing ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const result = await payload(response);
      if (!response.ok) throw new Error(message(result, `Annotation failed (${response.status})`));
      onSaved(result as ResearchAnnotation);
      onClose();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Annotation could not be saved");
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!target.annotation) return;
    setSaving(true);
    setError("");
    try {
      const response = await fetch(
        `/api/runs/${encodeURIComponent(runId)}/annotations/${encodeURIComponent(target.annotation.annotation_id)}`,
        { method: "DELETE" },
      );
      if (!response.ok) {
        const result = await payload(response);
        throw new Error(message(result, `Delete failed (${response.status})`));
      }
      onDeleted(target.annotation.annotation_id);
      onClose();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Annotation could not be deleted");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="workbench-backdrop annotation-backdrop" onMouseDown={onClose}>
      <section
        className="annotation-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="annotation-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header>
          <div>
            <span>Researcher-only record</span>
            <h2 id="annotation-title">{target.annotation ? "Edit annotation" : "Annotate moment"}</h2>
            <p>{target.label}</p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close annotation editor">×</button>
        </header>
        <div className="annotation-preview">{target.preview}</div>
        <label className="annotation-bookmark">
          <input
            type="checkbox"
            checked={bookmarked}
            onChange={(event) => setBookmarked(event.target.checked)}
          />
          <span>Bookmark this moment</span>
        </label>
        <label>
          <span>Research note</span>
          <textarea
            rows={5}
            value={note}
            onChange={(event) => setNote(event.target.value)}
            placeholder="Why is this moment important?"
          />
        </label>
        <label>
          <span>Tags</span>
          <input
            value={tags}
            onChange={(event) => setTags(event.target.value)}
            placeholder="position-shift, incentive, follow-up"
          />
          <small>Comma-separated · stored only in the researcher channel</small>
        </label>
        {error && <div className="workbench-error">{error}</div>}
        <footer>
          {target.annotation && (
            <button className="danger-action" type="button" disabled={saving} onClick={remove}>
              Delete annotation
            </button>
          )}
          <span />
          <button type="button" disabled={saving} onClick={onClose}>Cancel</button>
          <button
            className="primary-action"
            type="button"
            disabled={saving || (!bookmarked && !note.trim() && parsedTags.length === 0)}
            onClick={save}
          >
            {saving ? "Saving…" : "Save annotation"}
          </button>
        </footer>
      </section>
    </div>
  );
}

export default AnnotationEditorDialog;
