import { useEffect, useState } from "react";
import "./participant-roster.css";

type NamingTheme =
  | "neutral"
  | "trees"
  | "mountains"
  | "animals"
  | "rivers"
  | "constellations";

export type GeneratedParticipant = {
  id: string;
  display_name: string;
};

type RosterResponse = {
  generator_version: string;
  theme: NamingTheme;
  seed: number;
  participants: GeneratedParticipant[];
};

type ParticipantRosterSetupProps = {
  seed: number;
  participantCount: number;
  onManualStart: () => void;
  onGenerated: (participants: GeneratedParticipant[]) => void;
  onAdd: () => void;
  onReset: () => void;
};

const themeLabels: Record<NamingTheme, string> = {
  neutral: "Neutral numbers",
  trees: "Trees",
  mountains: "Mountains",
  animals: "Animals",
  rivers: "Rivers",
  constellations: "Constellations",
};

async function errorText(response: Response) {
  try {
    const payload = await response.json() as { detail?: unknown };
    if (typeof payload.detail === "string") return payload.detail;
  } catch {
    // The status fallback below remains safe and useful.
  }
  return `Roster generation failed (${response.status})`;
}

function ParticipantRosterSetup({
  seed,
  participantCount,
  onManualStart,
  onGenerated,
  onAdd,
  onReset,
}: ParticipantRosterSetupProps) {
  const [method, setMethod] = useState<"choose" | "manual" | "generate">("choose");
  const [count, setCount] = useState(4);
  const [theme, setTheme] = useState<NamingTheme>("neutral");
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState("");
  const [generatedLabel, setGeneratedLabel] = useState("");

  useEffect(() => {
    if (participantCount === 0 && method === "manual") setMethod("choose");
  }, [method, participantCount]);

  if (participantCount > 0) {
    return (
      <div className="participant-roster-toolbar">
        <div>
          <span>{generatedLabel ? "Generated roster" : "Manual roster"}</span>
          <strong>{participantCount} participant{participantCount === 1 ? "" : "s"}</strong>
          <p>
            {generatedLabel || "Every participant remains independently editable below."}
          </p>
        </div>
        <div>
          <button className="secondary-action" type="button" onClick={onAdd}>
            + Add participant
          </button>
          <button
            className="roster-reset"
            type="button"
            onClick={() => {
              setGeneratedLabel("");
              setMethod("choose");
              onReset();
            }}
          >
            Choose another method
          </button>
        </div>
      </div>
    );
  }

  if (method === "generate") {
    const generate = async () => {
      setGenerating(true);
      setError("");
      try {
        const response = await fetch("/api/participant-rosters", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ count, theme, seed }),
        });
        if (!response.ok) throw new Error(await errorText(response));
        const roster = await response.json() as RosterResponse;
        setGeneratedLabel(
          `${themeLabels[roster.theme]} · ${roster.generator_version} · seed ${roster.seed}`,
        );
        onGenerated(roster.participants);
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : "Roster generation failed");
      } finally {
        setGenerating(false);
      }
    };

    return (
      <section className="roster-generator">
        <header>
          <div>
            <span>Automatic setup</span>
            <h2>Generate participant roster</h2>
            <p>Names are selected deterministically from the experiment seed and written explicitly into the final YAML.</p>
          </div>
          <button type="button" className="roster-reset" onClick={() => setMethod("choose")}>
            Back to methods
          </button>
        </header>
        <div className="field-row">
          <label className="field">
            <span>Number of participants</span>
            <input
              type="number"
              min="1"
              max="32"
              value={count}
              onChange={(event) => setCount(Number(event.target.value))}
            />
            <small>Up to 32 participants. Provider costs grow with rounds × participants.</small>
          </label>
          <label className="field">
            <span>Naming theme</span>
            <select value={theme} onChange={(event) => setTheme(event.target.value as NamingTheme)}>
              {Object.entries(themeLabels).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
            <small>Neutral numbers are the lowest-priming default.</small>
          </label>
        </div>
        <div className="roster-variable-note">
          <strong>Names are visible experimental material</strong>
          <p>Display names appear in the public feed. A themed roster may influence participants, so Thoughtstage records every generated alias explicitly.</p>
        </div>
        {error && <div className="inline-error">{error}</div>}
        <button
          className="save-button roster-generate"
          type="button"
          disabled={generating || count < 1 || count > 32}
          onClick={() => void generate()}
        >
          {generating ? "Generating…" : `Generate ${count} participant${count === 1 ? "" : "s"}`}
        </button>
      </section>
    );
  }

  return (
    <section className="participant-methods">
      <div className="participant-method-heading">
        <span>Roster setup</span>
        <h2>How would you like to add participants?</h2>
        <p>Start from a hand-authored participant or generate a reproducible roster, then edit every model binding and persona individually.</p>
      </div>
      <div className="participant-method-grid">
        <button
          className="participant-method-card"
          type="button"
          onClick={() => {
            setMethod("manual");
            setGeneratedLabel("");
            onManualStart();
          }}
        >
          <span>01 · Direct control</span>
          <strong>Manually add participants</strong>
          <p>Create the first participant and use the existing detailed editor.</p>
          <i aria-hidden="true">→</i>
        </button>
        <button
          className="participant-method-card featured"
          type="button"
          onClick={() => setMethod("generate")}
        >
          <span>02 · Reproducible shortcut</span>
          <strong>Generate participant roster</strong>
          <p>Choose a count and naming theme; Thoughtstage generates seeded aliases.</p>
          <i aria-hidden="true">→</i>
        </button>
      </div>
    </section>
  );
}

export default ParticipantRosterSetup;
