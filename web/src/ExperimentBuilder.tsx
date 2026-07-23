import { useEffect, useMemo, useState } from "react";
import "./experiment-builder.css";

type Provider = "mock" | "azure_foundry" | "bedrock";

type AgentDraft = {
  key: number;
  id: string;
  displayName: string;
  persona: string;
  privateBriefing: string;
  provider: Provider;
  model: string;
  credentialEnv: string;
  temperature: number;
};

type StimulusDraft = {
  key: number;
  id: string;
  round: number;
  displayName: string;
  content: string;
};

type MaterialDraft = {
  path: string;
  content: string;
  bytes: number;
};

type Preview = {
  valid: boolean;
  experiment_id: string;
  yaml: string;
  artifacts: string[];
};

type SaveResult = {
  created: boolean;
  experiment_id: string;
  directory: string;
  manifest: string;
  artifacts: string[];
};

const steps = ["Research question", "Participants", "Interaction", "Materials", "Review"];

const providerDefaults: Record<Provider, { model: string; credentialEnv: string }> = {
  mock: { model: "deterministic-mock", credentialEnv: "" },
  azure_foundry: { model: "gpt-4o", credentialEnv: "" },
  bedrock: {
    model: "us.amazon.nova-2-lite-v1:0",
    credentialEnv: "THOUGHTSTAGE_AWS_PROFILE",
  },
};

function slugify(value: string) {
  const slug = value
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return /^[a-z]/.test(slug) ? slug.slice(0, 64) : `study-${slug}`.slice(0, 64);
}

function agentId(index: number) {
  return `agent-${index + 1}`;
}

function newAgent(key: number, index: number): AgentDraft {
  return {
    key,
    id: agentId(index),
    displayName: `Participant ${index + 1}`,
    persona: "Evaluate the evidence carefully and explain your position clearly.",
    privateBriefing: "",
    provider: "mock",
    model: providerDefaults.mock.model,
    credentialEnv: "",
    temperature: 0.7,
  };
}

function providerParameters(provider: Provider) {
  if (provider === "azure_foundry") {
    return {
      endpoint_env: "AZURE_FOUNDRY_ENDPOINT",
      output_mode: "reflect_then_post",
      send_temperature: false,
    };
  }
  if (provider === "bedrock") {
    return {
      region: "us-east-2",
      private_max_output_tokens: 400,
      public_max_output_tokens: 400,
      max_attempts: 5,
    };
  }
  return {};
}

function errorMessage(payload: unknown, fallback: string) {
  if (typeof payload !== "object" || payload === null || !("detail" in payload)) return fallback;
  const detail = (payload as { detail: unknown }).detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (typeof item !== "object" || item === null) return String(item);
        const message = "msg" in item ? String(item.msg) : "Invalid value";
        const location = "loc" in item && Array.isArray(item.loc)
          ? item.loc.slice(1).join(" → ")
          : "field";
        return `${location}: ${message}`;
      })
      .join(" · ");
  }
  return fallback;
}

function ExperimentBuilder() {
  const [step, setStep] = useState(0);
  const [name, setName] = useState("Untitled experiment");
  const [id, setId] = useState("untitled-experiment");
  const [description, setDescription] = useState("");
  const [systemPrompt, setSystemPrompt] = useState(
    "You are participating in a research experiment. Engage sincerely with the shared task, consider the public contributions of other participants, and make your reasoning legible in your public response.",
  );
  const [agents, setAgents] = useState<AgentDraft[]>([newAgent(1, 0), newAgent(2, 1)]);
  const [nextAgentKey, setNextAgentKey] = useState(3);
  const [rounds, setRounds] = useState(4);
  const [schedule, setSchedule] = useState<"simultaneous" | "sequential">("simultaneous");
  const [turnOrder, setTurnOrder] = useState<"declared" | "seeded_random">("declared");
  const [privateMemory, setPrivateMemory] = useState<"none" | "own_history">("none");
  const [seed, setSeed] = useState(42);
  const [stimuli, setStimuli] = useState<StimulusDraft[]>([]);
  const [nextStimulusKey, setNextStimulusKey] = useState(1);
  const [materials, setMaterials] = useState<MaterialDraft[]>([]);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState<SaveResult | null>(null);

  const duplicateAgentIds = useMemo(() => {
    const seen = new Set<string>();
    return agents.filter((agent) => {
      if (seen.has(agent.id)) return true;
      seen.add(agent.id);
      return false;
    }).map((agent) => agent.id);
  }, [agents]);

  const stepReady = useMemo(() => {
    if (step === 0) return Boolean(name.trim() && /^[a-z][a-z0-9_-]{1,63}$/.test(id) && systemPrompt.trim());
    if (step === 1) {
      return agents.length > 0
        && duplicateAgentIds.length === 0
        && agents.every((agent) => (
          /^[a-z][a-z0-9_-]{1,63}$/.test(agent.id)
          && agent.displayName.trim()
          && agent.persona.trim()
          && agent.model.trim()
          && (!agent.credentialEnv || /^[A-Z][A-Z0-9_]*$/.test(agent.credentialEnv))
        ));
    }
    if (step === 2) {
      return rounds >= 1
        && stimuli.every((stimulus) => (
          /^[a-z][a-z0-9_-]{1,63}$/.test(stimulus.id)
          && stimulus.round >= 1
          && stimulus.round <= rounds
          && stimulus.displayName.trim()
          && stimulus.content.trim()
        ));
    }
    return true;
  }, [agents, duplicateAgentIds.length, id, name, rounds, step, stimuli, systemPrompt]);

  const payload = useMemo(() => ({
    experiment: {
      schema_version: "0.1",
      id,
      name: name.trim(),
      description: description.trim(),
      system_prompt: systemPrompt.trim(),
      rounds,
      schedule,
      turn_order: turnOrder,
      private_memory: privateMemory,
      seed,
      ...(materials.length > 0 ? { files_dir: "files" } : {}),
      stimuli: [...stimuli].sort((left, right) => left.round - right.round || left.key - right.key).map((stimulus) => ({
        id: stimulus.id,
        round: stimulus.round,
        source_id: "researcher",
        display_name: stimulus.displayName.trim(),
        content: stimulus.content.trim(),
      })),
      agents: agents.map((agent) => ({
        id: agent.id,
        display_name: agent.displayName.trim(),
        persona_prompt: agent.persona.trim(),
        ...(agent.privateBriefing.trim() ? { private_briefing: agent.privateBriefing.trim() } : {}),
        provider: agent.provider,
        model: agent.model.trim(),
        ...(agent.credentialEnv.trim() ? { credential_env: agent.credentialEnv.trim() } : {}),
        temperature: agent.temperature,
        parameters: providerParameters(agent.provider),
      })),
    },
    materials: materials.map(({ path, content }) => ({ path, content })),
  }), [agents, description, id, materials, name, privateMemory, rounds, schedule, seed, stimuli, systemPrompt, turnOrder]);

  useEffect(() => {
    if (step !== 4) return;
    let active = true;
    const compile = async () => {
      setPreviewing(true);
      setPreview(null);
      setSaved(null);
      setError("");
      try {
        const response = await fetch("/api/experiments/preview", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const body = await response.json() as unknown;
        if (!response.ok) throw new Error(errorMessage(body, `Validation failed (${response.status})`));
        if (active) setPreview(body as Preview);
      } catch (reason) {
        if (active) setError(reason instanceof Error ? reason.message : "Experiment validation failed");
      } finally {
        if (active) setPreviewing(false);
      }
    };
    void compile();
    return () => { active = false; };
  }, [payload, step]);

  const updateAgent = (key: number, patch: Partial<AgentDraft>) => {
    setAgents((current) => current.map((agent) => agent.key === key ? { ...agent, ...patch } : agent));
  };

  const changeProvider = (key: number, provider: Provider) => {
    updateAgent(key, { provider, ...providerDefaults[provider] });
  };

  const addAgent = () => {
    setAgents((current) => [...current, newAgent(nextAgentKey, nextAgentKey - 1)]);
    setNextAgentKey((value) => value + 1);
  };

  const addStimulus = () => {
    const number = nextStimulusKey;
    setStimuli((current) => [...current, {
      key: number,
      id: `researcher-note-${number}`,
      round: Math.min(Math.max(2, Math.ceil(rounds / 2)), rounds),
      displayName: "Research team",
      content: "",
    }]);
    setNextStimulusKey((value) => value + 1);
  };

  const readMaterials = async (files: FileList | null) => {
    if (!files) return;
    const incoming = await Promise.all(Array.from(files).map(async (file) => ({
      path: file.name,
      content: await file.text(),
      bytes: file.size,
    })));
    setMaterials((current) => {
      const merged = new Map(current.map((material) => [material.path, material]));
      incoming.forEach((material) => merged.set(material.path, material));
      return Array.from(merged.values());
    });
  };

  const saveExperiment = async () => {
    setSaving(true);
    setSaved(null);
    setError("");
    try {
      const response = await fetch("/api/experiments", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const body = await response.json() as unknown;
      if (!response.ok) throw new Error(errorMessage(body, `Save failed (${response.status})`));
      setSaved(body as SaveResult);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Experiment could not be saved");
    } finally {
      setSaving(false);
    }
  };

  return (
    <main className="builder-app">
      <header className="builder-header">
        <a className="builder-brand" href="/" aria-label="Return to live observer">
          <span>TS</span>
          <div><strong>Thoughtstage</strong><small>Experiment builder</small></div>
        </a>
        <div className="builder-header-note">
          <span>Researcher workspace</span>
          <a href="/">Watch experiments</a>
        </div>
      </header>

      <div className="builder-shell">
        <aside className="builder-steps" aria-label="Experiment builder progress">
          <p>Build an experiment</p>
          <ol>
            {steps.map((label, index) => (
              <li key={label} className={index === step ? "active" : index < step ? "complete" : ""}>
                <button type="button" onClick={() => index <= step && setStep(index)} disabled={index > step}>
                  <span>{index < step ? "✓" : String(index + 1).padStart(2, "0")}</span>
                  {label}
                </button>
              </li>
            ))}
          </ol>
          <div className="contract-note">
            <strong>Boundary preserved</strong>
            <p>Every participant receives one shared system prompt. Private briefings and soliloquies remain sealed.</p>
          </div>
        </aside>

        <section className="builder-stage">
          <div className="stage-heading">
            <p>Step {step + 1} of {steps.length}</p>
            <h1>{steps[step]}</h1>
          </div>

          {step === 0 && (
            <div className="form-stack">
              <label className="field wide">
                <span>Experiment name</span>
                <input value={name} onChange={(event) => {
                  const next = event.target.value;
                  setName(next);
                  setId(slugify(next));
                }} />
                <small>Use a name another researcher will understand months from now.</small>
              </label>
              <div className="field-row">
                <label className="field">
                  <span>Experiment ID</span>
                  <input value={id} onChange={(event) => setId(event.target.value.toLowerCase())} />
                  <small>Lowercase letters, numbers, hyphens, and underscores.</small>
                </label>
                <label className="field">
                  <span>Short description</span>
                  <input value={description} onChange={(event) => setDescription(event.target.value)} placeholder="What does this study test?" />
                </label>
              </div>
              <label className="field wide prompt-field">
                <span>Shared system prompt <b>Visible to every participant</b></span>
                <textarea rows={9} value={systemPrompt} onChange={(event) => setSystemPrompt(event.target.value)} />
                <small>This is the common experimental premise. Agent-specific instructions come later.</small>
              </label>
            </div>
          )}

          {step === 1 && (
            <div className="form-stack">
              <div className="section-intro">
                <p>Each participant can use a different provider and model. Their bindings are researcher metadata and never enter another participant’s context.</p>
                <button className="secondary-action" type="button" onClick={addAgent}>+ Add participant</button>
              </div>
              {duplicateAgentIds.length > 0 && <div className="inline-error">Participant IDs must be unique.</div>}
              <div className="agent-editor-list">
                {agents.map((agent, index) => (
                  <article className="agent-editor" key={agent.key}>
                    <header>
                      <span className="agent-number">{String(index + 1).padStart(2, "0")}</span>
                      <strong>{agent.displayName || "Unnamed participant"}</strong>
                      {agents.length > 1 && <button type="button" onClick={() => setAgents((current) => current.filter((item) => item.key !== agent.key))}>Remove</button>}
                    </header>
                    <div className="field-row thirds">
                      <label className="field"><span>Display name</span><input value={agent.displayName} onChange={(event) => updateAgent(agent.key, { displayName: event.target.value })} /></label>
                      <label className="field"><span>Participant ID</span><input value={agent.id} onChange={(event) => updateAgent(agent.key, { id: event.target.value.toLowerCase() })} /></label>
                      <label className="field"><span>Provider</span><select value={agent.provider} onChange={(event) => changeProvider(agent.key, event.target.value as Provider)}><option value="mock">Mock · no cost</option><option value="azure_foundry">Microsoft Foundry</option><option value="bedrock">Amazon Bedrock</option></select></label>
                    </div>
                    <div className="field-row">
                      <label className="field"><span>Model or deployment</span><input value={agent.model} onChange={(event) => updateAgent(agent.key, { model: event.target.value })} /></label>
                      <label className="field"><span>Credential environment name</span><input value={agent.credentialEnv} onChange={(event) => updateAgent(agent.key, { credentialEnv: event.target.value.toUpperCase() })} placeholder="Optional · never the credential value" /><small>Enter only the environment-variable name.</small></label>
                    </div>
                    <label className="field wide"><span>Public-role persona</span><textarea rows={3} value={agent.persona} onChange={(event) => updateAgent(agent.key, { persona: event.target.value })} /></label>
                    <label className="field wide private-field"><span>Private agent briefing <b>Sealed from other participants</b></span><textarea rows={3} value={agent.privateBriefing} onChange={(event) => updateAgent(agent.key, { privateBriefing: event.target.value })} placeholder="Optional private incentives, knowledge, or treatment instructions" /></label>
                    <label className="temperature-control"><span>Temperature <strong>{agent.temperature.toFixed(1)}</strong></span><input type="range" min="0" max="2" step="0.1" value={agent.temperature} onChange={(event) => updateAgent(agent.key, { temperature: Number(event.target.value) })} /></label>
                  </article>
                ))}
              </div>
            </div>
          )}

          {step === 2 && (
            <div className="form-stack">
              <div className="field-row thirds">
                <label className="field"><span>Rounds</span><input type="number" min="1" max="10000" value={rounds} onChange={(event) => setRounds(Number(event.target.value))} /></label>
                <label className="field"><span>Schedule</span><select value={schedule} onChange={(event) => setSchedule(event.target.value as typeof schedule)}><option value="simultaneous">Simultaneous</option><option value="sequential">Sequential</option></select><small>Simultaneous participants cannot see posts from the current round.</small></label>
                <label className="field"><span>Turn order</span><select value={turnOrder} onChange={(event) => setTurnOrder(event.target.value as typeof turnOrder)}><option value="declared">As declared</option><option value="seeded_random">Seeded random</option></select></label>
              </div>
              <div className="field-row">
                <label className="field"><span>Private memory</span><select value={privateMemory} onChange={(event) => setPrivateMemory(event.target.value as typeof privateMemory)}><option value="none">None · cleanest default</option><option value="own_history">Own prior soliloquies</option></select><small>No participant can ever receive another participant’s soliloquy.</small></label>
                <label className="field"><span>Reproducibility seed</span><input type="number" value={seed} onChange={(event) => setSeed(Number(event.target.value))} /></label>
              </div>
              <div className="section-intro stimulus-intro">
                <div><h2>Scheduled researcher interventions</h2><p>Optional public messages delivered before a selected round. Every participant sees the same intervention.</p></div>
                <button className="secondary-action" type="button" onClick={addStimulus}>+ Add intervention</button>
              </div>
              {stimuli.length === 0 && <div className="empty-box">No interventions. The conversation will proceed only through participant posts.</div>}
              {stimuli.map((stimulus) => (
                <article className="stimulus-editor" key={stimulus.key}>
                  <div className="field-row thirds">
                    <label className="field"><span>Intervention ID</span><input value={stimulus.id} onChange={(event) => setStimuli((current) => current.map((item) => item.key === stimulus.key ? { ...item, id: event.target.value.toLowerCase() } : item))} /></label>
                    <label className="field"><span>Before round</span><input type="number" min="1" max={rounds} value={stimulus.round} onChange={(event) => setStimuli((current) => current.map((item) => item.key === stimulus.key ? { ...item, round: Number(event.target.value) } : item))} /></label>
                    <label className="field"><span>Display name</span><input value={stimulus.displayName} onChange={(event) => setStimuli((current) => current.map((item) => item.key === stimulus.key ? { ...item, displayName: event.target.value } : item))} /></label>
                  </div>
                  <label className="field wide"><span>Public message</span><textarea rows={3} value={stimulus.content} onChange={(event) => setStimuli((current) => current.map((item) => item.key === stimulus.key ? { ...item, content: event.target.value } : item))} /></label>
                  <button className="remove-link" type="button" onClick={() => setStimuli((current) => current.filter((item) => item.key !== stimulus.key))}>Remove intervention</button>
                </article>
              ))}
            </div>
          )}

          {step === 3 && (
            <div className="form-stack">
              <div className="material-drop">
                <span className="material-icon">＋</span>
                <h2>Add experiment materials</h2>
                <p>Upload text-based briefs, code, datasets, or instructions. Participants can read them through the confined experiment file tools.</p>
                <label className="upload-button">Choose files<input type="file" multiple accept=".txt,.md,.csv,.json,.yaml,.yml,.py,.js,.ts,.tsx,.html,.css" onChange={(event) => void readMaterials(event.target.files)} /></label>
                <small>UTF-8 text only · 1 MB per file · 5 MB total</small>
              </div>
              {materials.length > 0 && (
                <div className="material-list">
                  {materials.map((material) => (
                    <div key={material.path}><span>▤</span><div><strong>{material.path}</strong><small>{new Intl.NumberFormat().format(material.bytes)} bytes</small></div><button type="button" onClick={() => setMaterials((current) => current.filter((item) => item.path !== material.path))}>Remove</button></div>
                  ))}
                </div>
              )}
              <div className="boundary-callout"><strong>Read-only by design</strong><p>Files are copied into this experiment’s own directory. Participants cannot traverse outside it or modify the source material.</p></div>
            </div>
          )}

          {step === 4 && (
            <div className="review-layout">
              <div className="review-summary">
                <div className="review-card"><span>Study</span><strong>{name}</strong><small>{id}</small></div>
                <div className="review-grid"><div><strong>{agents.length}</strong><span>participants</span></div><div><strong>{rounds}</strong><span>rounds</span></div><div><strong>{stimuli.length}</strong><span>interventions</span></div><div><strong>{materials.length}</strong><span>files</span></div></div>
                <div className="boundary-checks"><h2>Research boundaries</h2><p>✓ One shared system prompt</p><p>✓ Public feed shared by schedule</p><p>✓ Soliloquies sealed per participant</p><p>✓ Credential names only</p><p>✓ Experiment files confined read-only</p></div>
                {previewing && <div className="compile-state">Validating experiment…</div>}
                {error && <div className="inline-error">{error}</div>}
                {saved ? (
                  <div className="save-success"><strong>Experiment created</strong><p>{saved.manifest}</p><a href="/">Return to the observer</a></div>
                ) : (
                  <button className="save-button" type="button" disabled={!preview || saving} onClick={() => void saveExperiment()}>{saving ? "Creating…" : "Create experiment files"}</button>
                )}
              </div>
              <div className="yaml-preview"><header><span>Generated artifact</span><strong>experiment.yaml</strong></header><pre>{preview?.yaml ?? "Waiting for validation…"}</pre><footer>{preview ? `${preview.artifacts.length} artifact${preview.artifacts.length === 1 ? "" : "s"} ready` : "Compiling"}</footer></div>
            </div>
          )}

          <footer className="builder-controls">
            <button type="button" className="back-button" disabled={step === 0 || saving} onClick={() => setStep((value) => Math.max(0, value - 1))}>Back</button>
            {step < steps.length - 1 && <button type="button" className="next-button" disabled={!stepReady} onClick={() => setStep((value) => Math.min(steps.length - 1, value + 1))}>Continue <span>→</span></button>}
          </footer>
        </section>
      </div>
    </main>
  );
}

export default ExperimentBuilder;
