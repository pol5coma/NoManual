import { useEffect, useRef, useState } from "react";

import {
  ask,
  getConversation,
  listProducts,
  type AskResponse,
  type Citation,
  type Product,
} from "./api";
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

// One thread per appliance, remembered across reloads. localStorage rather
// than a cookie: nothing here is sent to the server on its own, and the id is
// meaningless to anyone who does not already have the conversation.
const conversationKey = (productId: string) => `nomanual.conversation.${productId}`;

export default function App() {
  const [products, setProducts] = useState<Product[]>([]);
  const [productId, setProductId] = useState("");
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const endRef = useRef<HTMLDivElement>(null);

  // Declared once and reused: the effect loads the catalogue on mount, and the
  // upload panel calls the same function when a new manual lands.
  function refreshProducts() {
    listProducts()
      .then(setProducts)
      .catch(() =>
        setError("No se pudo cargar el catálogo. ¿Está el backend en marcha?"),
      );
  }

  // The empty dependency array is what makes this run once: React re-runs an
  // effect whenever a value in that array changes, and nothing changes in an
  // empty one.
  useEffect(refreshProducts, []);

  // Restores the thread for this appliance, if there is one. Clearing the
  // screen happens in the change handler instead: an effect that sets state
  // synchronously makes React render twice for one user action.
  useEffect(() => {
    const stored = productId && localStorage.getItem(conversationKey(productId));
    if (!stored) return;

    // Switching appliances twice quickly would otherwise let the first, slower
    // response paint over the second.
    let current = true;

    getConversation(stored)
      .then((conversation) => {
        if (!current) return;
        setConversationId(conversation.id);
        setMessages(
          conversation.messages.map((message) => ({
            role: message.role,
            text: message.content,
            citations: message.citations,
          })),
        );
      })
      .catch(() => {
        // The thread is gone - a reset database, a cleared row. Forgetting the
        // id is the recovery: the next question starts a new conversation.
        localStorage.removeItem(conversationKey(productId));
      });

    return () => {
      current = false;
    };
  }, [productId]);

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
    setError(null);
  }

  function startNewConversation() {
    if (productId) localStorage.removeItem(conversationKey(productId));
    setConversationId(null);
    setMessages([]);
    setError(null);
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
    } catch {
      setError("No se pudo obtener respuesta. Inténtalo de nuevo.");
    } finally {
      setLoading(false);
    }
  }

  const selected = products.find((product) => product.id === productId);

  return (
    <div className="app">
      <header className="header">
        <div className="brand">
          <h1>NoManual</h1>
          <span>Pregunta a tus manuales</span>
        </div>

        <div className="controls">
          <select
            value={productId}
            onChange={(event) => handleProductChange(event.target.value)}
          >
            <option value="">Elige tu aparato…</option>
            {products.map((product) => (
              <option key={product.id} value={product.id}>
                {product.brand} {product.model}
              </option>
            ))}
          </select>
          {conversationId && (
            <button type="button" className="link" onClick={startNewConversation}>
              Nueva conversación
            </button>
          )}
          <UploadPanel onUploaded={refreshProducts} />
        </div>
      </header>

      <main className="chat">
        {messages.length === 0 && (
          <p className="empty">
            {selected
              ? `Pregunta lo que quieras sobre tu ${selected.brand} ${selected.model}.`
              : "Elige un aparato para empezar."}
          </p>
        )}

        {messages.map((message, index) => (
          <Turn key={index} message={message} />
        ))}

        {loading && <div className="turn assistant thinking">Buscando en el manual…</div>}
        {error && <div className="error">{error}</div>}

        <div ref={endRef} />
      </main>

      <form className="composer" onSubmit={handleSubmit}>
        <input
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder={
            selected ? "¿Cada cuánto limpio el filtro?" : "Elige un aparato primero"
          }
          disabled={!productId || loading}
        />
        <button type="submit" disabled={!productId || !question.trim() || loading}>
          Preguntar
        </button>
      </form>
    </div>
  );
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
            <li key={citation.chunk_id}>página {citation.page}</li>
          ))}
        </ul>
      )}

      {response?.escalated && (
        <span className="badge escalated">derivado a soporte</span>
      )}
      {response && !response.escalated && !response.grounded && (
        <span className="badge ungrounded">sin fuente verificada</span>
      )}
    </div>
  );
}
