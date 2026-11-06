import { useEffect, useLayoutEffect, useRef, useState } from "react";

import "./architecture.css";

const lanes = [
  { id: "customer", number: "01", name: "Customer", description: "Customer journey" },
  { id: "frontend", number: "02", name: "React frontend", description: "Chat UI · Vite" },
  { id: "api", number: "03", name: "Python API", description: "FastAPI · validation" },
  { id: "agent", number: "04", name: "Agent orchestration", description: "Routing · memory" },
  { id: "services", number: "05", name: "RAG & tools", description: "Retrieval · LangChain" },
  { id: "data", number: "06", name: "Data & providers", description: "JSON demo store · AI" },
];

const scenarios = [
  {
    id: "policy",
    label: "Policy answer",
    category: "RAG",
    description: "Ground a policy response in approved source documents.",
    steps: [
      { id: "policy-ask", lane: "customer", title: "Ask a policy question", subtitle: "“What is your refund policy?”", detail: "The customer asks about a policy or FAQ. No account-specific information is needed." },
      { id: "policy-compose", lane: "frontend", title: "Compose chat request", subtitle: "Message + conversation ID", detail: "The React UI manages visible chat state and sends the message, conversation_id, and recent context as JSON." },
      { id: "policy-api", lane: "api", title: "Validate the request", subtitle: "POST /api/chat", detail: "FastAPI validates and normalises the request, checks moderation, and loads only the relevant conversation context." },
      { id: "policy-route", lane: "agent", title: "Choose the policy route", subtitle: "Intent → RAG", detail: "The request router identifies a policy question and selects retrieval-augmented generation rather than an account-data tool." },
      { id: "policy-retrieve", lane: "services", title: "Run hybrid retrieval", subtitle: "Mistral vectors + BM25", detail: "The retrieval service embeds the query, runs vector similarity and BM25 keyword search, and combines rankings with reciprocal rank fusion." },
      { id: "policy-evidence", lane: "data", title: "Read approved evidence", subtitle: "Policy chunks + metadata", detail: "Search uses ingested, approved policy chunks. The demo stores source documents, chunk text, metadata, and embeddings in JSON files." },
      { id: "policy-generate", lane: "services", title: "Generate a grounded answer", subtitle: "Groq · configured model", detail: "The model answers from retrieved evidence. If the evidence is missing or insufficient, the agent must say so instead of inventing details." },
      { id: "policy-response", lane: "api", title: "Return JSON response", subtitle: "Answer + source details", detail: "FastAPI returns the answer, route, source references, suggested actions, and memory diagnostics to the frontend." },
      { id: "policy-display", lane: "frontend", title: "Render answer & sources", subtitle: "Conversation state updated", detail: "The chat UI displays the answer and any source details, then retains the conversation context for a follow-up." },
      { id: "policy-done", lane: "customer", title: "Receive a sourced answer", subtitle: "Evidence-led support", detail: "The customer receives a response grounded in approved policy content, with uncertainty made explicit." },
    ],
  },
  {
    id: "order",
    label: "Order status",
    category: "Tool",
    description: "Authorize and retrieve current, customer-scoped order data.",
    steps: [
      { id: "order-ask", lane: "customer", title: "Ask about an order", subtitle: "“Where is order ORD-1001?”", detail: "The customer asks for private order or delivery information." },
      { id: "order-compose", lane: "frontend", title: "Send chat request", subtitle: "Message + session context", detail: "The React chat sends the question and conversation context to the backend as JSON." },
      { id: "order-validate", lane: "api", title: "Validate & authorize", subtitle: "Customer-scoped access", detail: "FastAPI validates the message and checks authorization before any private order or payment details are returned." },
      { id: "order-route", lane: "agent", title: "Select account-data route", subtitle: "Order / delivery intent", detail: "The router classifies the request and selects the relevant order or delivery tool." },
      { id: "order-tool", lane: "services", title: "Call a support tool", subtitle: "LangChain tool", detail: "A narrowly scoped tool validates its inputs and retrieves only the requested customer's order or delivery information." },
      { id: "order-record", lane: "data", title: "Read current records", subtitle: "Orders + delivery JSON", detail: "The demo tool reads the current order and delivery records from the JSON data store. MongoDB is a later storage target in this architecture." },
      { id: "order-answer", lane: "services", title: "Prepare the answer", subtitle: "Tool result → response", detail: "The response is based on the returned record; unsupported status or delivery details are not inferred." },
      { id: "order-return", lane: "api", title: "Return chat response", subtitle: "Answer + actions", detail: "The API returns the answer and relevant route, source, and action metadata." },
      { id: "order-render", lane: "frontend", title: "Display order update", subtitle: "Chat UI", detail: "The frontend renders the result in the conversation and keeps context available for follow-up questions." },
      { id: "order-done", lane: "customer", title: "See order information", subtitle: "Authorized result", detail: "The customer receives current information only after the backend authorization check succeeds." },
    ],
  },
  {
    id: "mixed",
    label: "Mixed product question",
    category: "RAG + tool",
    description: "Combine product policy evidence with live availability data.",
    steps: [
      { id: "mixed-ask", lane: "customer", title: "Ask a mixed question", subtitle: "“Is it in stock and under warranty?”", detail: "The customer needs both approved product or warranty guidance and current inventory information." },
      { id: "mixed-compose", lane: "frontend", title: "Send the message", subtitle: "Chat UI → API", detail: "React packages the message and conversation context into a JSON request." },
      { id: "mixed-api", lane: "api", title: "Validate request", subtitle: "FastAPI", detail: "The API validates the request and loads relevant conversation context before routing." },
      { id: "mixed-route", lane: "agent", title: "Choose combined route", subtitle: "RAG + relevant tools", detail: "The router recognises a question that needs both policy context and current product data." },
      { id: "mixed-rag", lane: "services", title: "Retrieve policy evidence", subtitle: "Warranty / product chunks", detail: "RAG searches approved product and warranty content with vector similarity and BM25." },
      { id: "mixed-stock", lane: "services", title: "Check availability", subtitle: "Inventory tool", detail: "A LangChain tool looks up current stock for the requested product." },
      { id: "mixed-data", lane: "data", title: "Read both data sources", subtitle: "Policy chunks + inventory", detail: "Policy evidence comes from the approved chunk store; stock is read from the operational product records." },
      { id: "mixed-generate", lane: "services", title: "Combine grounded results", subtitle: "Policy + live tool result", detail: "Generation keeps the policy answer separate from current stock information and does not infer unavailable facts." },
      { id: "mixed-response", lane: "api", title: "Return answer & sources", subtitle: "JSON response", detail: "FastAPI returns the combined answer with relevant source details and actions." },
      { id: "mixed-render", lane: "frontend", title: "Show both parts", subtitle: "Policy + current stock", detail: "The UI presents the policy information and availability result in the conversation." },
      { id: "mixed-done", lane: "customer", title: "Get a complete answer", subtitle: "Two evidence types", detail: "The customer sees which details come from policy content and which reflect current inventory." },
    ],
  },
  {
    id: "cancellation",
    label: "Order cancellation",
    category: "Confirmation",
    description: "Check eligibility, wait for explicit confirmation, then recheck and record.",
    steps: [
      { id: "cancel-ask", lane: "customer", title: "Request cancellation", subtitle: "Names an order", detail: "The customer asks to cancel an order. The request itself does not change order state." },
      { id: "cancel-send", lane: "frontend", title: "Send cancellation request", subtitle: "POST /api/chat", detail: "The chat UI sends the request to the API. A separate confirmation action is required before execution." },
      { id: "cancel-auth", lane: "api", title: "Verify access", subtitle: "Identity + authorization", detail: "The backend checks customer authorization before exposing or changing order information." },
      { id: "cancel-check-route", lane: "agent", title: "Check eligibility", subtitle: "Business rules + order state", detail: "The router orchestrates an eligibility check. The LLM alone does not decide whether cancellation is allowed." },
      { id: "cancel-read", lane: "data", title: "Read order & action records", subtitle: "Current state", detail: "The backend checks the order state and relevant cancellation/action records." },
      { id: "cancel-prompt", lane: "frontend", title: "Ask for confirmation", subtitle: "No change made yet", detail: "If eligible, the UI shows a clear confirmation prompt. Nothing changes until the customer explicitly confirms." },
      { id: "cancel-confirm", lane: "customer", title: "Confirm the action", subtitle: "Explicit customer choice", detail: "The customer confirms or declines. Declining leaves the order unchanged." },
      { id: "cancel-recheck", lane: "api", title: "Recheck before execution", subtitle: "Authorized confirmation", detail: "The final cancellation request rechecks authorization, eligibility, and order state on the server." },
      { id: "cancel-update", lane: "services", title: "Update order & audit", subtitle: "Cancellation workflow", detail: "The cancellation runs only after confirmation and successful server-side rechecks; the outcome is recorded for audit/history." },
      { id: "cancel-store", lane: "data", title: "Persist outcome", subtitle: "Demo JSON records", detail: "The demo updates the order record and durable cancellation history in JSON storage. Production needs a persistent concurrent-write-safe store." },
      { id: "cancel-result", lane: "frontend", title: "Show final outcome", subtitle: "Success or reason", detail: "The UI displays the authoritative result or the reason cancellation could not be completed." },
    ],
  },
  {
    id: "unknown",
    label: "Unknown / escalation",
    category: "Fallback",
    description: "Be transparent when evidence is missing and offer human support.",
    steps: [
      { id: "unknown-ask", lane: "customer", title: "Ask an unsupported question", subtitle: "No reliable evidence available", detail: "The customer asks something outside the available policies, records, or tool capabilities." },
      { id: "unknown-send", lane: "frontend", title: "Send the question", subtitle: "Chat UI → FastAPI", detail: "The frontend sends the message and conversation context as a JSON chat request." },
      { id: "unknown-check", lane: "api", title: "Validate & load context", subtitle: "Request checks", detail: "FastAPI validates the request and loads only relevant conversation context." },
      { id: "unknown-route", lane: "agent", title: "Select supported path", subtitle: "Intent routing", detail: "The router tries the relevant retrieval or tool path without treating a model guess as evidence." },
      { id: "unknown-evidence", lane: "services", title: "Check available evidence", subtitle: "RAG and/or tools", detail: "Retrieval or tools return no sufficiently reliable evidence to answer the question." },
      { id: "unknown-data", lane: "data", title: "No verified result", subtitle: "Evidence unavailable", detail: "Missing policy chunks or records remain unknown; the system must not invent an answer." },
      { id: "unknown-escalate", lane: "services", title: "Offer human support", subtitle: "Support ticket path", detail: "When appropriate, the app can create a support ticket and trigger a follow-up through the configured support services." },
      { id: "unknown-return", lane: "api", title: "Return transparent response", subtitle: "Answer + next action", detail: "The API returns a clear statement about what could not be verified and any appropriate support action." },
      { id: "unknown-render", lane: "frontend", title: "Display next steps", subtitle: "Chat UI", detail: "The frontend shows the uncertainty and the available human-support option." },
      { id: "unknown-done", lane: "customer", title: "Choose what to do next", subtitle: "No fabricated answer", detail: "The customer can provide more information or continue with human support." },
    ],
  },
];

function ArchitectureIcon({ name, size = 20 }) {
  const props = {
    "aria-hidden": "true",
    fill: "none",
    height: size,
    stroke: "currentColor",
    strokeLinecap: "round",
    strokeLinejoin: "round",
    strokeWidth: 1.7,
    viewBox: "0 0 24 24",
    width: size,
  };

  if (name === "map") {
    return <svg {...props}><path d="M3 6.5 8.5 4l7 2.5L21 4v13.5L15.5 20l-7-2.5L3 20V6.5Z" /><path d="M8.5 4v13.5M15.5 6.5V20" /></svg>;
  }
  if (name === "chat") {
    return <svg {...props}><path d="M20 11.5a7.5 7.5 0 0 1-7.5 7.5H6l-3 2 1-4.5a7.5 7.5 0 1 1 16-5Z" /><path d="M8 11h.01M12 11h.01M16 11h.01" strokeWidth="2.5" /></svg>;
  }
  if (name === "play") {
    return <svg {...props}><path d="m8 5 11 7-11 7V5Z" fill="currentColor" stroke="none" /></svg>;
  }
  if (name === "pause") {
    return <svg {...props}><path d="M8 5h3v14H8zM15 5h3v14h-3z" fill="currentColor" stroke="none" /></svg>;
  }
  if (name === "restart") {
    return <svg {...props}><path d="M4 11a8 8 0 1 1 1.8 5M4 5v6h6" /></svg>;
  }
  if (name === "arrow") {
    return <svg {...props}><path d="M5 12h14m-6-6 6 6-6 6" /></svg>;
  }
  return <svg {...props}><circle cx="12" cy="12" r="9" /><path d="M12 11v5m0-8h.01" /></svg>;
}

function StepCard({ step, index, state, selected, onSelect, setNodeRef }) {
  return (
    <button
      aria-current={state === "current" ? "step" : undefined}
      aria-label={`Step ${index + 1}: ${step.title}. ${step.subtitle}`}
      className={`architecture-step architecture-step-${state}${selected ? " architecture-step-selected" : ""}`}
      onClick={onSelect}
      ref={setNodeRef}
      type="button"
    >
      <span className="architecture-step-top">
        <span className="architecture-step-number">{String(index + 1).padStart(2, "0")}</span>
        <span className={`architecture-step-state architecture-step-state-${state}`}>
          {state === "complete" ? "Done" : state === "current" ? "Now" : "Next"}
        </span>
      </span>
      <strong>{step.title}</strong>
      <span className="architecture-step-subtitle">{step.subtitle}</span>
      <span className="architecture-step-more">View component <span aria-hidden="true">↗</span></span>
    </button>
  );
}

export default function ArchitectureDiagram() {
  const [scenarioId, setScenarioId] = useState(scenarios[0].id);
  const [currentStep, setCurrentStep] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [connections, setConnections] = useState([]);
  const canvasRef = useRef(null);
  const nodeRefs = useRef(new Map());
  const scenario = scenarios.find((item) => item.id === scenarioId) ?? scenarios[0];
  const selectedStep = scenario.steps[currentStep];

  useEffect(() => {
    document.title = "System architecture · Customer Support AI";
    return () => {
      document.title = "Customer Support";
    };
  }, []);

  useEffect(() => {
    if (!isPlaying) return undefined;
    const timer = window.setTimeout(() => {
      setCurrentStep((stepIndex) => {
        if (stepIndex >= scenario.steps.length - 1) {
          setIsPlaying(false);
          return stepIndex;
        }
        return stepIndex + 1;
      });
    }, 1200);
    return () => window.clearTimeout(timer);
  }, [currentStep, isPlaying, scenario.steps.length]);

  useLayoutEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;
    let frame = 0;
    const measure = () => {
      window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(() => {
        const bounds = canvas.getBoundingClientRect();
        const nextConnections = scenario.steps.slice(0, -1).map((step, index) => {
          const source = nodeRefs.current.get(step.id);
          const target = nodeRefs.current.get(scenario.steps[index + 1].id);
          if (!source || !target) return null;
          const sourceBounds = source.getBoundingClientRect();
          const targetBounds = target.getBoundingClientRect();
          return {
            id: step.id,
            x1: sourceBounds.right - bounds.left,
            y1: sourceBounds.top + sourceBounds.height / 2 - bounds.top,
            x2: targetBounds.left - bounds.left,
            y2: targetBounds.top + targetBounds.height / 2 - bounds.top,
          };
        }).filter(Boolean);
        setConnections(nextConnections);
      });
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(canvas);
    window.addEventListener("resize", measure);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", measure);
      window.cancelAnimationFrame(frame);
    };
  }, [scenario]);

  function chooseScenario(id) {
    const nextScenario = scenarios.find((item) => item.id === id);
    if (!nextScenario) return;
    setScenarioId(id);
    setCurrentStep(0);
    setIsPlaying(false);
  }

  function goToStep(index) {
    const nextIndex = Math.max(0, Math.min(index, scenario.steps.length - 1));
    setCurrentStep(nextIndex);
    if (nextIndex === scenario.steps.length - 1) setIsPlaying(false);
  }

  const progress = Math.round(((currentStep + 1) / scenario.steps.length) * 100);

  return (
    <div className="architecture-app">
      <aside className="architecture-sidebar">
        <a aria-label="Customer Support home" className="architecture-brand" href="/">
          <span className="architecture-brand-mark"><ArchitectureIcon name="map" size={22} /></span>
          <span><strong>Support AI</strong><small>System workspace</small></span>
        </a>
        <div className="architecture-sidebar-label">WORKSPACE</div>
        <nav aria-label="Architecture workspace" className="architecture-navigation">
          <a aria-current="page" className="architecture-nav-item architecture-nav-item-active" href="/architecture">
            <ArchitectureIcon name="map" />
            <span>Architecture map</span>
          </a>
          <a className="architecture-nav-item" href="/">
            <ArchitectureIcon name="chat" />
            <span>Customer chat</span>
            <span className="architecture-nav-arrow" aria-hidden="true">↗</span>
          </a>
        </nav>
        <div className="architecture-sidebar-note">
          <span className="architecture-note-icon"><ArchitectureIcon name="info" size={17} /></span>
          <strong>How to explore</strong>
          <p>Choose a request path, play it step by step, or select any component to inspect its role.</p>
        </div>
        <div className="architecture-sidebar-footer">
          <span className="architecture-status-dot" />
          <span>Architecture reference</span>
          <span className="architecture-status-version">v1.0</span>
        </div>
      </aside>

      <main className="architecture-main">
        <header className="architecture-topbar">
          <div className="architecture-breadcrumb">Workspace <span>/</span> Architecture</div>
          <a className="architecture-chat-link" href="/">
            <ArchitectureIcon name="chat" size={17} />
            Open support chat
            <span aria-hidden="true">↗</span>
          </a>
        </header>

        <div className="architecture-content">
          <section className="architecture-intro">
            <div>
              <div className="architecture-eyebrow"><span /> SYSTEM DESIGN</div>
              <h1>Customer support architecture</h1>
              <p>Follow a request from the first customer message through routing, retrieval or tools, and back to the chat.</p>
            </div>
            <span className="architecture-source-link">
              <ArchitectureIcon name="info" size={16} />
              Based on the architecture document
            </span>
          </section>

          <section aria-label="Request scenarios" className="architecture-scenarios">
            <div className="architecture-scenario-heading">
              <div><span className="architecture-section-kicker">REQUEST PATH</span><strong>Explore a flow</strong></div>
              <span className="architecture-scenario-count">{scenarios.length} scenarios</span>
            </div>
            <div className="architecture-scenario-tabs" role="tablist" aria-label="Request flow">
              {scenarios.map((item) => (
                <button
                  aria-selected={scenarioId === item.id}
                  className={`architecture-scenario-tab${scenarioId === item.id ? " architecture-scenario-tab-active" : ""}`}
                  key={item.id}
                  onClick={() => chooseScenario(item.id)}
                  role="tab"
                  type="button"
                >
                  <span className="architecture-tab-dot" />
                  <span>{item.label}</span>
                  <small>{item.category}</small>
                </button>
              ))}
            </div>
            <p className="architecture-scenario-description">{scenario.description}</p>
          </section>

          <section aria-label="Interactive swimlane diagram" className="architecture-diagram-panel">
            <div className="architecture-diagram-header">
              <div>
                <div className="architecture-diagram-title-row">
                  <h2>{scenario.label}</h2>
                  <span className="architecture-flow-badge"><span /> {scenario.category}</span>
                </div>
                <p>Swimlane view <span>·</span> {scenario.steps.length} steps <span>·</span> Select a card for details</p>
              </div>
              <div aria-label="Playback controls" className="architecture-controls">
                <button aria-label="Restart flow" className="architecture-control-button architecture-restart-button" onClick={() => { setIsPlaying(false); goToStep(0); }} type="button">
                  <ArchitectureIcon name="restart" size={17} />
                </button>
                <button
                  aria-label={isPlaying ? "Pause flow" : "Play flow"}
                  className="architecture-play-button"
                  onClick={() => {
                    if (currentStep === scenario.steps.length - 1) goToStep(0);
                    setIsPlaying((playing) => !playing);
                  }}
                  type="button"
                >
                  <ArchitectureIcon name={isPlaying ? "pause" : "play"} size={16} />
                  {isPlaying ? "Pause" : "Play flow"}
                </button>
                <button aria-label="Advance one step" className="architecture-control-button architecture-next-button" disabled={currentStep === scenario.steps.length - 1} onClick={() => goToStep(currentStep + 1)} type="button">
                  <ArchitectureIcon name="arrow" size={17} />
                </button>
              </div>
            </div>

            <div className="architecture-progress-row">
              <span className="architecture-progress-label">FLOW PROGRESS</span>
              <div aria-label={`Flow progress: ${progress}%`} className="architecture-progress-track" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress}>
                <span style={{ width: `${progress}%` }} />
              </div>
              <span className="architecture-progress-count">{String(currentStep + 1).padStart(2, "0")} <i>/</i> {String(scenario.steps.length).padStart(2, "0")}</span>
            </div>

            <div className="architecture-diagram-scroll">
              <div
                className="architecture-diagram-grid"
                ref={canvasRef}
                style={{
                  gridTemplateColumns: `196px repeat(${scenario.steps.length}, 208px)`,
                  gridTemplateRows: `44px repeat(${lanes.length}, 132px)`,
                  width: `${196 + scenario.steps.length * 208}px`,
                }}
              >
                <div className="architecture-grid-corner">
                  <span>PARTICIPANTS</span>
                  <span aria-hidden="true">↓</span>
                </div>
                {scenario.steps.map((step, index) => (
                  <div className={`architecture-column-heading${index === currentStep ? " architecture-column-heading-current" : ""}`} key={`heading-${step.id}`} style={{ gridColumn: index + 2, gridRow: 1 }}>
                    <span>{String(index + 1).padStart(2, "0")}</span>
                    <i />
                    <small>{index === 0 ? "START" : index === scenario.steps.length - 1 ? "RESPONSE" : "STEP"}</small>
                  </div>
                ))}

                {lanes.map((lane, laneIndex) => (
                  <div className="architecture-lane-label" key={`lane-${lane.id}`} style={{ gridColumn: 1, gridRow: laneIndex + 2 }}>
                    <span className="architecture-lane-number">{lane.number}</span>
                    <span><strong>{lane.name}</strong><small>{lane.description}</small></span>
                  </div>
                ))}
                {lanes.flatMap((lane, laneIndex) =>
                  scenario.steps.map((step, stepIndex) => {
                    const laneStep = step.lane === lane.id;
                    const state = stepIndex < currentStep ? "complete" : stepIndex === currentStep ? "current" : "future";
                    return (
                      <div
                        aria-hidden={!laneStep ? "true" : undefined}
                        className={`architecture-grid-cell${laneStep ? " architecture-grid-cell-filled" : ""}${stepIndex === currentStep ? " architecture-grid-cell-current" : ""}`}
                        key={`${lane.id}-${step.id}`}
                        style={{ gridColumn: stepIndex + 2, gridRow: laneIndex + 2 }}
                      >
                        {laneStep && (
                          <StepCard
                            index={stepIndex}
                            onSelect={() => goToStep(stepIndex)}
                            selected={currentStep === stepIndex}
                            setNodeRef={(element) => {
                              if (element) nodeRefs.current.set(step.id, element);
                              else nodeRefs.current.delete(step.id);
                            }}
                            state={state}
                            step={step}
                          />
                        )}
                      </div>
                    );
                  }),
                )}

                <svg aria-hidden="true" className="architecture-connectors" height="100%" width="100%">
                  <defs>
                    <marker id="architecture-arrow" markerHeight="7" markerWidth="7" orient="auto" refX="5.6" refY="3.5">
                      <path d="M0 0 7 3.5 0 7Z" />
                    </marker>
                  </defs>
                  {connections.map((connection, index) => {
                    const dx = connection.x2 - connection.x1;
                    const curve = Math.max(20, dx * 0.44);
                    const active = index < currentStep;
                    const current = index === currentStep;
                    return (
                      <path
                        className={`architecture-connector${active ? " architecture-connector-active" : current ? " architecture-connector-current" : ""}`}
                        d={`M ${connection.x1} ${connection.y1} C ${connection.x1 + curve} ${connection.y1}, ${connection.x2 - curve} ${connection.y2}, ${connection.x2} ${connection.y2}`}
                        key={connection.id}
                        markerEnd="url(#architecture-arrow)"
                      />
                    );
                  })}
                </svg>
              </div>
            </div>
            <div className="architecture-pan-hint"><span aria-hidden="true">↔</span> Scroll horizontally to follow the full request path</div>
          </section>

          <section aria-live="polite" className="architecture-detail-panel">
            <div className="architecture-detail-icon"><ArchitectureIcon name="info" size={19} /></div>
            <div className="architecture-detail-copy">
              <div className="architecture-detail-overline">
                <span>COMPONENT DETAIL</span>
                <i />
                <span>{lanes.find((lane) => lane.id === selectedStep?.lane)?.name}</span>
              </div>
              <h3>{selectedStep?.title}</h3>
              <p>{selectedStep?.detail}</p>
            </div>
            <div className="architecture-detail-step">
              <span>STEP</span>
              <strong>{String(scenario.steps.findIndex((step) => step.id === selectedStep?.id) + 1).padStart(2, "0")}<i> / {String(scenario.steps.length).padStart(2, "0")}</i></strong>
            </div>
          </section>

          <footer className="architecture-footer">
            <span>Based on the documented demo architecture</span>
            <span><i /> JSON demo store <b>·</b> MongoDB migration target</span>
          </footer>
        </div>
      </main>
    </div>
  );
}
