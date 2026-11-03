import {
  type ChangeEvent,
  type ReactNode,
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import {
  Button,
  Checkbox,
  InlineAlert,
  Label,
  Select,
  Tabs,
  Tag,
} from "@lego/connect-components-react";
import { markdownToHtml } from "./markdown";

/* ─── Tone context ─── */

type Tone = "technical" | "business" | "childlike";
const ToneContext = createContext<Tone>("technical");
function useTone(): Tone {
  return useContext(ToneContext);
}

/* ─── Discovery types ─── */

type RepoInfo = { path: string; name: string };
type MigrationScenario = { file: string; label: string; scenario: string };
type DriftScenario = {
  spec: string;
  label: string;
  scenario: string;
  whatsWrong: string;
  expectedCatches: string[];
  severity: string;
};
type EntityInfo = {
  name: string;
  shared: boolean;
  repoCount: number;
  repos: string[];
  filesByRepo: Record<string, string[]>;
};

type RepoPair = {
  repoA: string;
  repoB: string;
  nameA: string;
  nameB: string;
  sharedEntities: string[];
};

type ApiSpec = { path: string; title: string };
type FrontendDir = { path: string; label: string };

type DiscoveryData = {
  repos: RepoInfo[];
  migrationScenarios: MigrationScenario[];
  driftScenarios: DriftScenario[];
  apiSpecs: ApiSpec[];
  frontendDirs: FrontendDir[];
};

/* ─── Shared types & helpers ─── */

type ToolResult = {
  markdown: string;
  exit_code: number;
  duration: number;
  isError?: boolean;
};

const CLIENT_TIMEOUT_MS = 200_000;

async function callApi(
  endpoint: string,
  body: Record<string, unknown>,
  signal?: AbortSignal,
): Promise<ToolResult> {
  const resp = await fetch(`/api/${endpoint}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ error: resp.statusText }));
    return {
      markdown: `**Error ${resp.status}:** ${err.error ?? "Unknown error"}`,
      exit_code: 1,
      duration: 0,
      isError: true,
    };
  }
  return resp.json();
}

/* ─── useToolRunner hook ─── */

function useToolRunner() {
  const [result, setResult] = useState<ToolResult | null>(null);
  const [loading, setLoading] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const tone = useTone();

  const run = useCallback(
    async (endpoint: string, body: Record<string, unknown>) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      const timeoutId = setTimeout(
        () => controller.abort(),
        CLIENT_TIMEOUT_MS,
      );

      setLoading(true);
      setResult(null);

      try {
        const data = await callApi(endpoint, { ...body, tone }, controller.signal);
        if (!controller.signal.aborted) setResult(data);
      } catch (err: unknown) {
        if (!controller.signal.aborted) {
          const message =
            err instanceof Error ? err.message : "Unknown error";
          setResult({
            markdown: `**Network error:** ${message}`,
            exit_code: 1,
            duration: 0,
            isError: true,
          });
        }
      } finally {
        clearTimeout(timeoutId);
        if (!controller.signal.aborted) setLoading(false);
      }
    },
    [tone],
  );

  return { result, loading, run };
}

/* ─── Output display ─── */

function OutputDisplay({
  result,
  loading,
}: {
  result: ToolResult | null;
  loading: boolean;
}) {
  if (loading) {
    return (
      <div className="loading-placeholder">
        Analysing… this may take a moment.
      </div>
    );
  }
  if (!result) return null;

  const statusVariant = result.isError
    ? "negative"
    : result.exit_code === 0
      ? "positive"
      : "negative";
  const statusLabel = result.isError
    ? "Error"
    : result.exit_code === 0
      ? "Clean"
      : "Issues found";

  return (
    <div>
      <div className="result-bar">
        <Tag variant={statusVariant} aria-label="Result status">
          {statusLabel}
        </Tag>
        {!result.isError && (
          <Tag variant="neutral" aria-label="Duration">
            {result.duration}s
          </Tag>
        )}
      </div>
      <div
        className="output-area"
        dangerouslySetInnerHTML={{ __html: markdownToHtml(result.markdown) }}
      />
    </div>
  );
}

/* ─── Reusable components ─── */

function Field({
  id,
  label,
  children,
}: {
  id: string;
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="field-group">
      <Label forId={id}>{label}</Label>
      {children}
    </div>
  );
}

function RepoSelect({
  id,
  label,
  repos,
  value,
  onChange,
}: {
  id: string;
  label: string;
  repos: RepoInfo[];
  value: string;
  onChange: (path: string) => void;
}) {
  return (
    <Field id={id} label={label}>
      <Select
        id={id}
        value={value}
        onChange={(e: ChangeEvent<HTMLSelectElement>) =>
          onChange(e.target.value)
        }
      >
        {repos.map((r) => (
          <option key={r.path} value={r.path}>
            {r.name}
          </option>
        ))}
      </Select>
    </Field>
  );
}

/* ─── Context input ─── */

function ContextInput({
  value,
  onChange,
}: {
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div className="context-input">
      <label className="context-label" htmlFor="context-field">
        🎯 Focus Area <span className="context-hint">(optional — leave empty for full scope)</span>
      </label>
      <textarea
        id="context-field"
        className="context-textarea"
        placeholder="e.g. &quot;authentication and authorization&quot;, &quot;DNS redirect domain model&quot;, &quot;database connection handling&quot;, &quot;error handling patterns&quot;…"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        rows={2}
      />
    </div>
  );
}

/* ─── Panel description ─── */

function PanelDescription({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <div className="panel-description">
      <h2 className="panel-title">{title}</h2>
      <p className="panel-subtitle">{description}</p>
    </div>
  );
}

/* ─── Tool panels ─── */

function MigrationPanel({
  scenarios,
}: {
  scenarios: MigrationScenario[];
}) {
  const [idx, setIdx] = useState("0");
  const [context, setContext] = useState("");
  const { result, loading, run } = useToolRunner();

  if (scenarios.length === 0) {
    return (
      <InlineAlert variant="informative" showIcon>
        <InlineAlert.Content>
          No migration scenarios found. Add .cs files under scenarios/ to get
          started.
        </InlineAlert.Content>
      </InlineAlert>
    );
  }

  return (
    <div className="tool-form">
      <Field id="migration-scenario" label="Scenario">
        <Select
          id="migration-scenario"
          value={idx}
          onChange={(e: ChangeEvent<HTMLSelectElement>) =>
            setIdx(e.target.value)
          }
        >
          {scenarios.map((s, i) => (
            <option key={s.file} value={String(i)}>
              {s.label}
            </option>
          ))}
        </Select>
      </Field>
      <ContextInput value={context} onChange={setContext} />
      <Button
        variant="primary"
        onClick={() =>
          run("review-migration", { file: scenarios[Number(idx)].file, context })
        }
        loading={loading}
        loadingText="Reviewing…"
      >
        Review Migration
      </Button>
      <OutputDisplay result={result} loading={loading} />
    </div>
  );
}

function DriftPanel({
  scenarios,
  apiSpecs,
  frontendDirs,
}: {
  scenarios: DriftScenario[];
  apiSpecs: ApiSpec[];
  frontendDirs: FrontendDir[];
}) {
  const [idx, setIdx] = useState("0");
  const [oldSpec, setOldSpec] = useState(apiSpecs[0]?.path ?? "");
  const [frontend, setFrontend] = useState(frontendDirs[0]?.path ?? "");
  const [context, setContext] = useState("");
  const { result, loading, run } = useToolRunner();

  const active = scenarios[Number(idx)];

  if (scenarios.length === 0) {
    return (
      <InlineAlert variant="informative" showIcon>
        <InlineAlert.Content>
          No contract drift scenarios found. Add modified-spec.yaml files under
          scenarios/ to test API contract changes.
        </InlineAlert.Content>
      </InlineAlert>
    );
  }

  return (
    <div className="tool-form">
      <Field id="drift-scenario" label="Breaking Change Scenario">
        <Select
          id="drift-scenario"
          value={idx}
          onChange={(e: ChangeEvent<HTMLSelectElement>) =>
            setIdx(e.target.value)
          }
        >
          {scenarios.map((s, i) => (
            <option key={s.spec} value={String(i)}>
              {s.label}
            </option>
          ))}
        </Select>
      </Field>

      {active && (
        <div className="scenario-preview">
          <div className="scenario-header">
            <Tag
              variant={active.severity === "breaking" ? "negative" : "neutral"}
              aria-label="Severity"
            >
              {active.severity}
            </Tag>
            <strong>{active.label}</strong>
          </div>
          {active.whatsWrong && (
            <p className="scenario-description">{active.whatsWrong}</p>
          )}
          {active.expectedCatches.length > 0 && (
            <div className="scenario-catches">
              <span className="catches-label">AI should detect:</span>
              <ul>
                {active.expectedCatches.map((c, i) => (
                  <li key={i}>{c}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      <div className="form-row">
        {apiSpecs.length > 0 && (
          <Field id="drift-oldspec" label="📄 Baseline API Spec — the original contract to compare against">
            <Select
              id="drift-oldspec"
              value={oldSpec}
              onChange={(e: ChangeEvent<HTMLSelectElement>) =>
                setOldSpec(e.target.value)
              }
            >
              {apiSpecs.map((s) => (
                <option key={s.path} value={s.path}>
                  {s.title} — {s.path}
                </option>
              ))}
            </Select>
          </Field>
        )}
        {frontendDirs.length > 0 && (
          <Field id="drift-frontend" label="💻 Frontend Source — scanned for references to changed API fields">
            <Select
              id="drift-frontend"
              value={frontend}
              onChange={(e: ChangeEvent<HTMLSelectElement>) =>
                setFrontend(e.target.value)
              }
            >
              {frontendDirs.map((d) => (
                <option key={d.path} value={d.path}>
                  {d.label}
                </option>
              ))}
            </Select>
          </Field>
        )}
      </div>
      <ContextInput value={context} onChange={setContext} />
      <Button
        variant="primary"
        onClick={() => {
          run("check-drift", {
            spec: active.spec,
            oldSpec,
            frontend,
            context,
          });
        }}
        loading={loading}
        loadingText="Analysing impact…"
      >
        Check Contract Drift
      </Button>
      <OutputDisplay result={result} loading={loading} />
    </div>
  );
}

function SecretsPanel({ repos }: { repos: RepoInfo[] }) {
  const [repo, setRepo] = useState(repos[0]?.path ?? "");
  const [context, setContext] = useState("");
  const { result, loading, run } = useToolRunner();

  return (
    <div className="tool-form">
      <RepoSelect
        id="secrets-repo"
        label="Repository"
        repos={repos}
        value={repo}
        onChange={setRepo}
      />
      <ContextInput value={context} onChange={setContext} />
      <Button
        variant="primary"
        onClick={() => run("scan-secrets", { repoPath: repo, context })}
        loading={loading}
        loadingText="Scanning…"
      >
        Scan for Secrets
      </Button>
      <OutputDisplay result={result} loading={loading} />
    </div>
  );
}

function ModelDriftPanel({ repos }: { repos: RepoInfo[] }) {
  const [selectedRepos, setSelectedRepos] = useState<Record<string, boolean>>(
    () => Object.fromEntries(repos.slice(0, 4).map((r) => [r.path, false])),
  );
  const [entities, setEntities] = useState<EntityInfo[]>([]);
  const [pairs, setPairs] = useState<RepoPair[]>([]);
  const [entity, setEntity] = useState("");
  const [selectedPair, setSelectedPair] = useState("");
  const [context, setContext] = useState("");
  const [scanning, setScanning] = useState(false);
  const scanGenRef = useRef(0);
  const { result, loading, run } = useToolRunner();

  const activeRepoPaths = repos
    .filter((r) => selectedRepos[r.path])
    .map((r) => r.path);

  function toggleRepo(path: string) {
    return (_e: ChangeEvent<HTMLInputElement>, checked: boolean) => {
      setSelectedRepos((prev) => ({ ...prev, [path]: checked }));
    };
  }

  async function scanEntities() {
    if (activeRepoPaths.length < 2) return;
    const gen = ++scanGenRef.current;
    setScanning(true);
    setEntities([]);
    setPairs([]);
    setEntity("");
    setSelectedPair("");
    try {
      const resp = await fetch("/api/scan-entities", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ repos: activeRepoPaths }),
      });
      // Discard stale response if selection changed during fetch
      if (gen !== scanGenRef.current) return;
      const data = await resp.json();
      const shared = (data.entities as EntityInfo[]).filter((e) => e.shared);
      const fetchedPairs = (data.pairs ?? []) as RepoPair[];
      setEntities(shared);
      setPairs(fetchedPairs);
      if (shared.length > 0) setEntity(shared[0].name);
      if (fetchedPairs.length > 0) setSelectedPair("0");
    } catch {
      /* ignore */
    } finally {
      if (gen === scanGenRef.current) setScanning(false);
    }
  }

  // Auto-scan when selected repos change (debounced by requiring 2+)
  useEffect(() => {
    if (activeRepoPaths.length >= 2) {
      scanEntities();
    } else {
      setEntities([]);
      setPairs([]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(activeRepoPaths)]);

  // Filter pairs that contain the selected entity
  const relevantPairs = pairs.filter((p) =>
    p.sharedEntities.includes(entity),
  );

  function runDrift() {
    if (!entity || relevantPairs.length === 0) return;

    if (relevantPairs.length === 1) {
      // Single pair — run directly
      const pair = relevantPairs[0];
      run("check-model-drift", {
        repoA: pair.repoA,
        repoB: pair.repoB,
        entity,
        context,
      });
    } else if (selectedPair) {
      // User selected a specific pair
      const pair = relevantPairs[Number(selectedPair)];
      if (pair) {
        run("check-model-drift", {
          repoA: pair.repoA,
          repoB: pair.repoB,
          entity,
          context,
        });
      }
    }
  }

  return (
    <div className="tool-form">
      <div>
        <div style={{ marginBottom: "var(--ds-layout-spacing-50)" }}>
          <strong>Select repos to compare (2 or more):</strong>
        </div>
        <div className="checkbox-group">
          {repos.map((r) => (
            <Checkbox
              key={r.path}
              label={r.name}
              checked={selectedRepos[r.path] ?? false}
              onChange={toggleRepo(r.path)}
            />
          ))}
        </div>
      </div>

      {activeRepoPaths.length < 2 && (
        <InlineAlert variant="informative" showIcon>
          <InlineAlert.Content>
            Select at least 2 repositories to scan for shared domain entities.
          </InlineAlert.Content>
        </InlineAlert>
      )}

      {scanning && (
        <div className="loading-placeholder">
          Scanning {activeRepoPaths.length} repos for shared entities…
        </div>
      )}

      {!scanning && entities.length > 0 && (
        <Field id="modeldrift-entity" label="Shared Entity">
          <Select
            id="modeldrift-entity"
            value={entity}
            onChange={(e: ChangeEvent<HTMLSelectElement>) => {
              setEntity(e.target.value);
              setSelectedPair("0");
            }}
          >
            {entities.map((e) => (
              <option key={e.name} value={e.name}>
                {e.name} (in {e.repoCount} repos: {e.repos.join(", ")})
              </option>
            ))}
          </Select>
        </Field>
      )}

      {!scanning && relevantPairs.length > 1 && (
        <Field id="modeldrift-pair" label="Compare Pair">
          <Select
            id="modeldrift-pair"
            value={selectedPair}
            onChange={(e: ChangeEvent<HTMLSelectElement>) =>
              setSelectedPair(e.target.value)
            }
          >
            {relevantPairs.map((p, i) => (
              <option key={`${p.nameA}-${p.nameB}`} value={String(i)}>
                {p.nameA} ↔ {p.nameB}
              </option>
            ))}
          </Select>
        </Field>
      )}

      {!scanning && entities.length === 0 && activeRepoPaths.length >= 2 && (
        <InlineAlert variant="informative" showIcon>
          <InlineAlert.Content>
            No shared entity classes found across selected repos.
          </InlineAlert.Content>
        </InlineAlert>
      )}

      <ContextInput value={context} onChange={setContext} />

      <Button
        variant="primary"
        onClick={runDrift}
        loading={loading}
        disabled={!entity || relevantPairs.length === 0 || scanning}
        loadingText="Comparing…"
      >
        Check Model Drift
      </Button>
      <OutputDisplay result={result} loading={loading} />
    </div>
  );
}

function ArchDocPanel({ repos }: { repos: RepoInfo[] }) {
  const [selected, setSelected] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(repos.map((r) => [r.path, true])),
  );
  const [context, setContext] = useState("");
  const { result, loading, run } = useToolRunner();

  function toggle(path: string) {
    return (_e: ChangeEvent<HTMLInputElement>, checked: boolean) => {
      setSelected((prev) => ({ ...prev, [path]: checked }));
    };
  }

  const repoPaths = repos
    .filter((r) => selected[r.path])
    .map((r) => r.path);

  return (
    <div className="tool-form">
      <div className="checkbox-group">
        {repos.map((r) => (
          <Checkbox
            key={r.path}
            label={r.name}
            checked={selected[r.path] ?? false}
            onChange={toggle(r.path)}
          />
        ))}
      </div>
      <ContextInput value={context} onChange={setContext} />
      <Button
        variant="primary"
        onClick={() => run("generate-arch-doc", { repoPaths, context })}
        loading={loading}
        disabled={repoPaths.length === 0}
        loadingText="Generating…"
      >
        Generate Architecture Doc
      </Button>
      <OutputDisplay result={result} loading={loading} />
    </div>
  );
}

function RequirementsPanel({ repos }: { repos: RepoInfo[] }) {
  const [selected, setSelected] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(repos.map((r, i) => [r.path, i < 1])),
  );
  const [context, setContext] = useState("");
  const { result, loading, run } = useToolRunner();

  function toggle(path: string) {
    return (_e: ChangeEvent<HTMLInputElement>, checked: boolean) => {
      setSelected((prev) => ({ ...prev, [path]: checked }));
    };
  }

  const repoPaths = repos
    .filter((r) => selected[r.path])
    .map((r) => r.path);

  return (
    <div className="tool-form">
      <div>
        <div style={{ marginBottom: "var(--ds-layout-spacing-50)" }}>
          <strong>Select repositories to analyse:</strong>
        </div>
        <div className="checkbox-group">
          {repos.map((r) => (
            <Checkbox
              key={r.path}
              label={r.name}
              checked={selected[r.path] ?? false}
              onChange={toggle(r.path)}
            />
          ))}
        </div>
      </div>
      <ContextInput value={context} onChange={setContext} />
      <Button
        variant="primary"
        onClick={() => run("extract-requirements", { repoPaths, context })}
        loading={loading}
        disabled={repoPaths.length === 0}
        loadingText={`Analysing ${repoPaths.length} repo${repoPaths.length > 1 ? "s" : ""}…`}
      >
        Extract Business Rules{repoPaths.length > 1 ? ` (${repoPaths.length} repos)` : ""}
      </Button>
      <OutputDisplay result={result} loading={loading} />
    </div>
  );
}

function ScenarioPlannerPanel({ repos }: { repos: RepoInfo[] }) {
  const [selected, setSelected] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(repos.map((r, i) => [r.path, i < 1])),
  );
  const [scenario, setScenario] = useState("");
  const [context, setContext] = useState("");
  const { result, loading, run } = useToolRunner();

  function toggle(path: string) {
    return (_e: ChangeEvent<HTMLInputElement>, checked: boolean) => {
      setSelected((prev) => ({ ...prev, [path]: checked }));
    };
  }

  const repoPaths = repos
    .filter((r) => selected[r.path])
    .map((r) => r.path);

  return (
    <div className="tool-form">
      <div>
        <div style={{ marginBottom: "var(--ds-layout-spacing-50)" }}>
          <strong>Select repositories:</strong>
        </div>
        <div className="checkbox-group">
          {repos.map((r) => (
            <Checkbox
              key={r.path}
              label={r.name}
              checked={selected[r.path] ?? false}
              onChange={toggle(r.path)}
            />
          ))}
        </div>
      </div>

      <div className="context-input">
        <label className="context-label" htmlFor="scenario-field">
          💡 What do you want to enable or change?
        </label>
        <textarea
          id="scenario-field"
          className="context-textarea scenario-textarea"
          placeholder='e.g. "Add Redis caching for DNS redirect lookups", "Enable HTTPS/TLS termination at the Kubernetes ingress", "Add audit logging for all admin actions", "Migrate from PostgreSQL 11 to 15"…'
          value={scenario}
          onChange={(e) => setScenario(e.target.value)}
          rows={3}
        />
      </div>

      <ContextInput value={context} onChange={setContext} />

      <Button
        variant="primary"
        onClick={() =>
          run("scenario-planner", { repoPaths, scenario, context })
        }
        loading={loading}
        disabled={repoPaths.length === 0 || !scenario.trim()}
        loadingText="Analysing scenario…"
      >
        Analyse Scenario
      </Button>
      <OutputDisplay result={result} loading={loading} />
    </div>
  );
}

function AuditPanel({ repos }: { repos: RepoInfo[] }) {
  const [repo, setRepo] = useState(repos[0]?.path ?? "");
  const [context, setContext] = useState("");
  const { result, loading, run } = useToolRunner();

  return (
    <div className="tool-form">
      <RepoSelect
        id="audit-repo"
        label="Repository"
        repos={repos}
        value={repo}
        onChange={setRepo}
      />
      <ContextInput value={context} onChange={setContext} />
      <Button
        variant="primary"
        onClick={() => run("audit-deps", { repoPath: repo, context })}
        loading={loading}
        loadingText="Auditing…"
      >
        Run Dependency Audit
      </Button>
      <OutputDisplay result={result} loading={loading} />
    </div>
  );
}

/* ─── App ─── */

export default function App() {
  const [discovery, setDiscovery] = useState<DiscoveryData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [allRepos, setAllRepos] = useState<RepoInfo[]>([]);
  const [selectedPaths, setSelectedPaths] = useState<Set<string>>(new Set());
  const [repoFilter, setRepoFilter] = useState("");
  const [customPath, setCustomPath] = useState("");
  const [tone, setTone] = useState<Tone>("technical");

  // Derived: active repos for tools
  const repos = allRepos.filter((r) => selectedPaths.has(r.path));

  // Load discovery data on mount
  useEffect(() => {
    fetch("/api/discover")
      .then((r) => r.json())
      .then((data: DiscoveryData) => {
        setDiscovery(data);
        setAllRepos(data.repos);
        // Select all by default
        setSelectedPaths(new Set(data.repos.map((r: RepoInfo) => r.path)));
      })
      .catch((err) => setError(err.message));
  }, []);

  function toggleRepoSelection(path: string) {
    setSelectedPaths((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  }

  function selectAll() {
    setSelectedPaths(new Set(allRepos.map((r) => r.path)));
  }

  function deselectAll() {
    setSelectedPaths(new Set());
  }

  function addRepo() {
    const path = customPath.trim();
    if (!path) return;
    if (allRepos.some((r) => r.path === path)) {
      // Already known — just select it
      setSelectedPaths((prev) => new Set([...prev, path]));
    } else {
      const name = path.split("/").pop() ?? path;
      setAllRepos((prev) => [...prev, { path, name }]);
      setSelectedPaths((prev) => new Set([...prev, path]));
    }
    setCustomPath("");
  }

  const filterLower = repoFilter.toLowerCase();
  const filteredRepos = allRepos.filter((r) =>
    r.name.toLowerCase().includes(filterLower),
  );

  if (error) {
    return (
      <div className="app-shell">
        <InlineAlert variant="negative" showIcon>
          <InlineAlert.Content>
            Failed to connect to server: {error}
          </InlineAlert.Content>
        </InlineAlert>
      </div>
    );
  }

  if (!discovery) {
    return (
      <div className="app-shell">
        <div className="loading-placeholder">Loading toolkit…</div>
      </div>
    );
  }

  return (
    <ToneContext.Provider value={tone}>
    <div className="app-shell">
      <header className="app-header">
        <div className="header-row">
          <h1>🏗️ Station Retrofit</h1>
          <span className="header-badge">
            {repos.length} repos · 8 AI tools · 3-layer architecture
          </span>
          <div className="tone-selector">
            <label htmlFor="tone-select" className="tone-label">🎭 Output style</label>
            <select
              id="tone-select"
              className="tone-dropdown"
              value={tone}
              onChange={(e) => setTone(e.target.value as Tone)}
            >
              <option value="technical">🔧 Technical</option>
              <option value="business">💼 Business</option>
              <option value="childlike">🧒 Simple (Kid-friendly)</option>
            </select>
          </div>
        </div>
        <p>AI-Powered Brownfield System Enhancement — LEGO Engineering Meetup 2026</p>
      </header>

      {/* Collapsible repo management */}
      <details className="repo-section" open>
        <summary className="repo-summary">
          <strong>Repositories</strong>
          <span className="repo-count">
            {selectedPaths.size} of {allRepos.length} selected
          </span>
        </summary>
        <div className="repo-body">
          <div className="repo-toolbar">
            <input
              className="repo-filter"
              type="text"
              placeholder="🔍 Filter repositories… (Enter to select matches)"
              value={repoFilter}
              onChange={(e) => setRepoFilter(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && repoFilter.trim()) {
                  setSelectedPaths(new Set(filteredRepos.map((r) => r.path)));
                  setRepoFilter("");
                }
              }}
            />
            <button
              type="button"
              className="repo-action-btn"
              onClick={selectAll}
              title="Select all"
            >
              Select all
            </button>
            <button
              type="button"
              className="repo-action-btn"
              onClick={deselectAll}
              title="Deselect all"
            >
              Deselect all
            </button>
          </div>

          <div className="repo-picker">
            {filteredRepos.length === 0 && (
              <div className="repo-empty">
                No repositories match "{repoFilter}"
              </div>
            )}
            {filteredRepos.map((r) => {
              const isSelected = selectedPaths.has(r.path);
              return (
                <button
                  key={r.path}
                  type="button"
                  className={`repo-chip ${isSelected ? "repo-chip--selected" : "repo-chip--unselected"}`}
                  onClick={() => toggleRepoSelection(r.path)}
                  title={isSelected ? `Deselect ${r.name}` : `Select ${r.name}`}
                >
                  <span className="repo-chip-icon">{isSelected ? "✓" : "+"}</span>
                  <span className="repo-chip-name">{r.name}</span>
                </button>
              );
            })}
          </div>

          <div className="repo-add">
            <input
              className="repo-input"
              type="text"
              placeholder="Add custom repo path…"
              value={customPath}
              onChange={(e) => setCustomPath(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && addRepo()}
            />
            <Button variant="neutral" onClick={addRepo} disabled={!customPath.trim()}>
              Add
            </Button>
          </div>
        </div>
      </details>

      <Tabs>
        <Tabs.List>
          {/* ── Understand ── */}
          <Tabs.Tab
            value="requirements"
            text="Business Intel"
            iconName="book-open"
          />
          <Tabs.Tab
            value="archdoc"
            text="Architecture"
            iconName="file-text"
          />
          <Tabs.Tab
            value="scenario"
            text="Scenario Plan"
            iconName="lightbulb"
          />
          {/* ── Secure ── */}
          <Tabs.Tab
            value="secrets"
            text="Secrets"
            iconName="lock"
          />
          <Tabs.Tab
            value="audit"
            text="Dependencies"
            iconName="box-archive"
          />
          <Tabs.Tab
            value="migration"
            text="Migrations"
            iconName="file-database"
          />
          {/* ── Monitor ── */}
          <Tabs.Tab
            value="modeldrift"
            text="Model Drift"
            iconName="split"
          />
          <Tabs.Tab
            value="drift"
            text="Contract Drift"
            iconName="arrow-right-arrow-left"
          />
        </Tabs.List>

        {/* ── Understand ── */}
        <Tabs.Panel
          value="requirements"
          style={{ paddingTop: "var(--ds-layout-spacing-200)" }}
        >
          <PanelDescription
            title="Business Intelligence"
            description="Reverse-engineer business rules, domain models, requirements, and tech stack from code. Perfect for brownfield systems where documentation is missing or outdated."
          />
          <RequirementsPanel repos={repos} />
        </Tabs.Panel>
        <Tabs.Panel
          value="archdoc"
          style={{ paddingTop: "var(--ds-layout-spacing-200)" }}
        >
          <PanelDescription
            title="Architecture Documentation"
            description="Generate architecture documentation from repository structure, dependencies, and code patterns across one or more services."
          />
          <ArchDocPanel repos={repos} />
        </Tabs.Panel>

        <Tabs.Panel
          value="scenario"
          style={{ paddingTop: "var(--ds-layout-spacing-200)" }}
        >
          <PanelDescription
            title="Scenario Planning"
            description="Describe a feature or change you want to enable. The AI analyses your codebase to produce an implementation plan, risk assessment, and effort estimate."
          />
          <ScenarioPlannerPanel repos={repos} />
        </Tabs.Panel>

        {/* ── Secure ── */}
        <Tabs.Panel
          value="secrets"
          style={{ paddingTop: "var(--ds-layout-spacing-200)" }}
        >
          <PanelDescription
            title="Secret Scanner"
            description="Detect leaked credentials, API keys, and hardcoded secrets using pattern matching and entropy analysis, then classify with AI."
          />
          <SecretsPanel repos={repos} />
        </Tabs.Panel>
        <Tabs.Panel
          value="audit"
          style={{ paddingTop: "var(--ds-layout-spacing-200)" }}
        >
          <PanelDescription
            title="Dependency Audit"
            description="Scan for outdated, deprecated, or vulnerable dependencies. Checks package manifests across all supported ecosystems."
          />
          <AuditPanel repos={repos} />
        </Tabs.Panel>
        <Tabs.Panel
          value="migration"
          style={{ paddingTop: "var(--ds-layout-spacing-200)" }}
        >
          <PanelDescription
            title="Migration Safety Review"
            description="Review database migration files for data loss risks, missing rollback logic, and ordering issues."
          />
          <MigrationPanel scenarios={discovery.migrationScenarios} />
        </Tabs.Panel>

        {/* ── Monitor ── */}
        <Tabs.Panel
          value="modeldrift"
          style={{ paddingTop: "var(--ds-layout-spacing-200)" }}
        >
          <PanelDescription
            title="Domain Model Drift"
            description="Detect when the same domain entity (e.g. DnsRedirect) has diverged across services — different fields, types, or constraints."
          />
          <ModelDriftPanel repos={repos} />
        </Tabs.Panel>
        <Tabs.Panel
          value="drift"
          style={{ paddingTop: "var(--ds-layout-spacing-200)" }}
        >
          <PanelDescription
            title="API Contract Drift"
            description="Compare an API spec against its implementation to catch breaking changes before they reach production."
          />
          <DriftPanel
            scenarios={discovery.driftScenarios}
            apiSpecs={discovery.apiSpecs}
            frontendDirs={discovery.frontendDirs}
          />
        </Tabs.Panel>
      </Tabs>
    </div>
    </ToneContext.Provider>
  );
}
