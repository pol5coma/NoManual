import { useCallback, useEffect, useRef, useState } from "react";

import {
  ask,
  deleteConversation,
  getConversation,
  listConversations,
  listProducts,
  type AskResponse,
  type Citation,
  type ConversationSummary,
  type ManualUpload,
  type Product,
} from "./api";
import IngestionPanel from "./IngestionPanel";
import Sidebar from "./Sidebar";
import UploadPanel from "./UploadPanel";
import "./App.css";

// One turn of the conversation. The assistant's turns carry the metadata the
// backend produced - citations, whether it was grounded, whether it gave up -
// because that is what separates this from a chatbot with a nicer logo.
interface Message {
  role: "user" | "assistant";
  text: string;
  // Present on turns answered in this session. A turn restored from the server
  // only carries its citations, which is why they are kept separately.
  response?: AskResponse;
  citations?: Citation[];
}

// The thread last opened for each appliance, so a reload comes back to it.
// localStorage rather than a cookie: nothing here is sent to the server on its
// own, and the id is meaningless to anyone who does not have the conversation.
const conversationKey = (productId: string) => `nomanual.conversation.${productId}`;
const DEV_MODE_KEY = "nomanual.devMode";

export default function App() {
  const [products, setProducts] = useState<Product[]>([]);
  const [productId, setProductId] = useState("");
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Developer mode adds timings and the numbers each stage produced. The
  // stages themselves are shown to everyone: someone who has just uploaded a
  // 130-page PDF deserves to see it being read, split and indexed.
  const [devMode, setDevMode] = useState(
    () => localStorage.getItem(DEV_MODE_KEY) === "true",
  );
  const [ingestingId, setIngestingId] = useState<string | null>(null);
  // Lifted out of UploadPanel because the ingestion card has to know: the form
  // floats over that corner, and the card slides aside rather than hiding
  // under it.
  const [uploadOpen, setUploadOpen] = useState(false);

  const endRef = useRef<HTMLDivElement>(null);

  // Declared once and reused: the effect loads the catalogue on mount, and the
  // upload panel calls the same function when a new manual lands.
  function refreshProducts() {
    listProducts()
      .then(setProducts)
      .catch(() =>
        setError("Could not load the catalogue. Is the backend running?"),
      );
  }

  // useCallback keeps the same function across renders, so the effect below
  // does not re-run on every keystroke just because a new one was created.
  const refreshConversations = useCallback((id: string) => {
    listConversations(id)
      .then(setConversations)
      .catch(() => setConversations([]));
  }, []);

  // The empty dependency array is what makes this run once: React re-runs an
  // effect whenever a value in that array changes, and nothing changes in an
  // empty one.
  useEffect(refreshProducts, []);

  // Restores the thread for this appliance and lists the rest. Clearing the
  // screen happens in the change handler instead: an effect that sets state
  // synchronously makes React render twice for one user action.
  useEffect(() => {
    if (!productId) return;

    refreshConversations(productId);

    const stored = localStorage.getItem(conversationKey(productId));
    if (!stored) return;

    // Switching appliances twice quickly would otherwise let the first, slower
    // response paint over the second.
    let current = true;

    getConversation(stored)
      .then((conversation) => {
        if (!current) return;
        setConversationId(conversation.id);
        setMessages(toMessages(conversation.messages));
      })
      .catch(() => {
        // The thread is gone - a reset database, a cleared row. Forgetting the
        // id is the recovery: the next question starts a new conversation.
        localStorage.removeItem(conversationKey(productId));
      });

    return () => {
      current = false;
    };
  }, [productId, refreshConversations]);

  // Keeps the newest message in view. Runs after every change to messages.
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Another appliance means another conversation, because retrieval is scoped
  // to the product: carrying the thread over would mix an oven's history into
  // a washing machine's search.
  function handleProductChange(id: string) {
    setProductId(id);
    setConversationId(null);
    setMessages([]);
    setConversations([]);
    setError(null);
  }

  function startNewConversation() {
    if (productId) localStorage.removeItem(conversationKey(productId));
    setConversationId(null);
    setMessages([]);
    setError(null);
  }

  async function openConversation(id: string) {
    setError(null);
    try {
      const conversation = await getConversation(id);
      setConversationId(conversation.id);
      setMessages(toMessages(conversation.messages));
      localStorage.setItem(conversationKey(productId), conversation.id);
    } catch {
      setError("Could not open that conversation.");
    }
  }

  async function removeConversation(id: string) {
    try {
      await deleteConversation(id);
      if (id === conversationId) startNewConversation();
      refreshConversations(productId);
    } catch {
      setError("Could not delete that conversation.");
    }
  }

  function handleUploaded(manual: ManualUpload) {
    refreshProducts();
    // The id is kept even with the panel hidden, so turning developer mode on
    // mid-ingestion shows what is already happening.
    setIngestingId(manual.id);
  }

  function toggleDevMode() {
    const next = !devMode;
    setDevMode(next);
    localStorage.setItem(DEV_MODE_KEY, String(next));
  }

  async function handleSubmit(event: React.FormEvent) {
    // A <form> reloads the page by default. In a single-page app that would
    // throw away all the state we are keeping in memory.
    event.preventDefault();

    const text = question.trim();
    if (!text || !productId || loading) return;

    // Show the user's turn immediately rather than after the answer arrives:
    // the request takes seconds, and a screen that does nothing feels broken.
    setMessages((current) => [...current, { role: "user", text }]);
    setQuestion("");
    setLoading(true);
    setError(null);

    try {
      const response = await ask(text, productId, conversationId ?? undefined);

      // The first answer is what names the thread. Everything after it just
      // keeps sending the same id back.
      setConversationId(response.conversation_id);
      localStorage.setItem(conversationKey(productId), response.conversation_id);

      setMessages((current) => [
        ...current,
        { role: "assistant", text: response.answer, response },
      ]);
      refreshConversations(productId);
    } catch {
      setError("Could not get an answer. Try again.");
    } finally {
      setLoading(false);
    }
  }

  const selected = products.find((product) => product.id === productId);
  const productName = selected ? `${selected.brand} ${selected.model}` : null;

  return (
    <div className="shell">
      <Sidebar
        conversations={conversations}
        activeId={conversationId}
        productName={productName}
        onSelect={openConversation}
        onNew={startNewConversation}
        onDelete={removeConversation}
      />

      <div className="app">
        <header className="header">
          <div className="brand">
            <h1>NoManual</h1>
            <span>Ask your manuals</span>
          </div>

          <div className="controls">
            <select
              value={productId}
              onChange={(event) => handleProductChange(event.target.value)}
            >
              <option value="">Choose your appliance…</option>
              {products.map((product) => (
                <option key={product.id} value={product.id}>
                  {product.brand} {product.model}
                </option>
              ))}
            </select>

            <UploadPanel
              open={uploadOpen}
              onOpenChange={setUploadOpen}
              onUploaded={handleUploaded}
            />

            <button
              type="button"
              className={devMode ? "toggle on" : "toggle"}
              onClick={toggleDevMode}
              title="Shows the ingestion pipeline step by step"
            >
              Developer mode
            </button>
          </div>
        </header>

        {ingestingId && (
          <IngestionPanel
            manualId={ingestingId}
            detailed={devMode}
            shifted={uploadOpen}
            onClose={() => setIngestingId(null)}
          />
        )}

        <main className="chat">
          {messages.length === 0 && (
            <p className="empty">
              {selected
                ? `Ask anything about your ${productName}.`
                : "Choose an appliance to start."}`
            </p>
          )}

          {messages.map((message, index) => (
            <Turn key={index} message={message} />
          ))}

          {loading && (
            <div className="turn assistant thinking">Searching the manual…</div>
          )}
          {error && <div className="error">{error}</div>}

          <div ref={endRef} />
        </main>

        <form className="composer" onSubmit={handleSubmit}>
          <input
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder={
              selected ? "How often should I clean the filter?" : "Choose an appliance first"
            }
            disabled={!productId || loading}
          />
          <button
            type="submit"
            className="button primary"
            disabled={!productId || !question.trim() || loading}
          >
            Ask
          </button>
        </form>
      </div>
    </div>
  );
}

// The server returns messages, the chat renders turns. One shape conversion,
// in one place.
function toMessages(
  messages: { role: "user" | "assistant"; content: string; citations: Citation[] }[],
): Message[] {
  return messages.map((message) => ({
    role: message.role,
    text: message.content,
    citations: message.citations,
  }));
}

function Turn({ message }: { message: Message }) {
  const { response } = message;
  // Answered in this session, or restored from the server: the sources are
  // shown either way, so a reload does not turn a cited answer into a claim.
  const citations = response?.citations ?? message.citations ?? [];

  return (
    <div className={`turn ${message.role}`}>
      <p>{message.text}</p>

      {citations.length > 0 && (
        <ul className="citations">
          {citations.map((citation) => (
            <li key={citation.chunk_id}>page {citation.page}</li>
          ))}
        </ul>
      )}

      {response?.escalated && (
        <span className="badge escalated">handed to support</span>
      )}
      {response && !response.escalated && !response.grounded && (
        <span className="badge ungrounded">no verified source</span>
      )}
    </div>
  );
}
