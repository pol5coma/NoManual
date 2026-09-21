import type { ConversationSummary } from "./api";

interface Props {
  conversations: ConversationSummary[];
  activeId: string | null;
  // Null until an appliance is chosen: there is nothing to list before that,
  // because a conversation belongs to one product.
  productName: string | null;
  onSelect: (conversationId: string) => void;
  onNew: () => void;
  onDelete: (conversationId: string) => void;
}

export default function Sidebar({
  conversations,
  activeId,
  productName,
  onSelect,
  onNew,
  onDelete,
}: Props) {
  return (
    <nav className="sidebar">
      <div className="sidebar-head">
        <span className="sidebar-product">{productName ?? "Sin aparato"}</span>
        <button
          type="button"
          className="button primary block"
          onClick={onNew}
          disabled={!productName}
        >
          Nueva conversación
        </button>
      </div>

      <ul className="threads">
        {conversations.map((conversation) => (
          <li
            key={conversation.id}
            className={conversation.id === activeId ? "thread active" : "thread"}
          >
            <button
              type="button"
              className="thread-open"
              onClick={() => onSelect(conversation.id)}
            >
              <span className="thread-title">
                {conversation.title ?? "Conversación sin título"}
              </span>
              <span className="thread-meta">
                {formatDate(conversation.last_message_at ?? conversation.created_at)}
                {" · "}
                {conversation.message_count} mensajes
              </span>
            </button>

            <button
              type="button"
              className="thread-delete"
              title="Eliminar conversación"
              onClick={() => onDelete(conversation.id)}
            >
              ×
            </button>
          </li>
        ))}

        {productName && conversations.length === 0 && (
          <li className="threads-empty">Todavía no hay conversaciones.</li>
        )}
      </ul>
    </nav>
  );
}

// Today as a time, anything older as a date: in a list of threads the useful
// signal is "this morning" versus "last week", not the exact second.
function formatDate(value: string): string {
  const date = new Date(value);
  const today = new Date();
  const sameDay =
    date.getDate() === today.getDate() &&
    date.getMonth() === today.getMonth() &&
    date.getFullYear() === today.getFullYear();

  return sameDay
    ? date.toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" })
    : date.toLocaleDateString("es-ES", { day: "numeric", month: "short" });
}
