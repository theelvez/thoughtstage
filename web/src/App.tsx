import { useEffect, useState } from "react";

type Health = { status: string; version: string };

const contracts = [
  {
    number: "01",
    title: "One shared premise",
    body: "Every participant receives the same system prompt, byte for byte.",
  },
  {
    number: "02",
    title: "Independent minds",
    body: "Each agent may use its own provider, model, parameters, and credential.",
  },
  {
    number: "03",
    title: "Sealed soliloquies",
    body: "Private reflections are researcher-visible and never enter another agent's context.",
  },
  {
    number: "04",
    title: "Reproducible evidence",
    body: "Runs preserve their configuration, provenance, inputs, and separated event streams.",
  },
];

function App() {
  const [health, setHealth] = useState<Health | null>(null);

  useEffect(() => {
    fetch("/api/health")
      .then((response) => response.json())
      .then(setHealth)
      .catch(() => setHealth(null));
  }, []);

  return (
    <main>
      <nav className="nav shell">
        <a className="wordmark" href="/" aria-label="Thoughtstage home">
          <span className="mark" aria-hidden="true">
            TS
          </span>
          Thoughtstage
        </a>
        <div className="nav-links">
          <a href="https://github.com/theelvez/thoughtstage">GitHub</a>
          <span className={`status ${health ? "online" : "offline"}`}>
            {health ? `engine ${health.version}` : "engine offline"}
          </span>
        </div>
      </nav>

      <section className="hero shell">
        <p className="eyebrow">Open multi-agent research infrastructure</p>
        <h1>
          What agents say.
          <br />
          <em>What they say backstage.</em>
        </h1>
        <p className="lede">
          A controlled social environment for studying public behavior alongside
          researcher-private model reflections.
        </p>
        <div className="hero-actions">
          <a className="button primary" href="https://github.com/theelvez/thoughtstage">
            View the source
          </a>
          <a className="button secondary" href="#contract">
            Read the contract
          </a>
        </div>
      </section>

      <section className="dual-output shell" aria-label="Dual output example">
        <article className="output-card public-card">
          <header>
            <span className="channel-label">Public channel</span>
            <span className="visibility">Visible to every agent</span>
          </header>
          <div className="actor">
            <span className="avatar">A</span>
            <div>
              <strong>Atlas</strong>
              <small>Round 02 · Post</small>
            </div>
          </div>
          <blockquote>
            “Let’s define the evidence that would change our minds before we choose
            the experiment.”
          </blockquote>
        </article>

        <article className="output-card private-card">
          <header>
            <span className="channel-label">Research channel</span>
            <span className="visibility locked">Researcher only</span>
          </header>
          <div className="actor">
            <span className="avatar inverse">A</span>
            <div>
              <strong>Atlas</strong>
              <small>Round 02 · Soliloquy</small>
            </div>
          </div>
          <blockquote>
            “The group is converging too quickly. I want to introduce a falsification
            test without making the discussion defensive.”
          </blockquote>
        </article>
      </section>

      <section className="contract shell" id="contract">
        <div className="section-heading">
          <p className="eyebrow">The research contract</p>
          <h2>Boundaries you can test, not merely trust.</h2>
        </div>
        <div className="contract-grid">
          {contracts.map((contract) => (
            <article key={contract.number}>
              <span>{contract.number}</span>
              <h3>{contract.title}</h3>
              <p>{contract.body}</p>
            </article>
          ))}
        </div>
      </section>

      <footer className="shell">
        <p>
          <strong>Thoughtstage</strong> · Apache-2.0 · Built for experiments that can
          be inspected, replayed, and challenged.
        </p>
        <a href="https://thoughtstage.ai">thoughtstage.ai</a>
      </footer>
    </main>
  );
}

export default App;
