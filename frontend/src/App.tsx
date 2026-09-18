import { useEffect, useRef, useState } from "react";

import { ask, listProducts, type AskResponse, type Product } from "./api";
import "./App.css";

// One turn of the conversation. The assistant's turns carry the metadata the
// backend produced - citations, whether it was grounded, whether it gave up -
// because that is what separates this from a chatbot with a nicer logo.
interface Message {
  role: "user" | "assistant";
  text: string;
  response?: AskResponse;
}

export default function App() {
  const [products, setProducts] = useState<Product[]>([]);
  const [productId, setProductId] = useState("");
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const endRef = useRef<HTMLDivElement>(null);

  // Runs once after the first render. The empty dependency array is what makes
  // it "once": React re-runs an effect whenever a value in that array changes,
  // and nothing ever changes in an empty one.
  useEffect(() => {
    listProducts()
      .then(setProducts)
      .catch(() => setError("No se pudo cargar el catálogo. ¿Está el backend en marcha?"));
  }, []);

  // Keeps the newest message in view. Runs after every change to messages.
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

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
      const response = await ask(text, productId);
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
        <h1>NoManual</h1>
        <select
          value={productId}
          onChange={(event) => setProductId(event.target.value)}
        >
          <option value="">Elige tu aparato…</option>
          {products.map((product) => (
            <option key={product.id} value={product.id}>
              {product.brand} {product.model}
            </option>
          ))}
        </select>
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

  return (
    <div className={`turn ${message.role}`}>
      <p>{message.text}</p>

      {response && response.citations.length > 0 && (
        <ul className="citations">
          {response.citations.map((citation) => (
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
