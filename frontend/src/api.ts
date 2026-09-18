// Everything that talks to the backend lives here.
//
// Kept apart from the components on purpose: a component should worry about
// what the user sees, not about URLs, headers or JSON shapes. 
// When the API changes, one file changes.

const API_URL = import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000";

// These describe the shape of what the backend sends. TypeScript checks them
// while you write, then disappears: none of this exists at runtime, so if the
// backend returns something else, nothing here will notice.
//
// That is the opposite of Pydantic on the server, which validates for real.

export interface Product {
  id: string;
  brand: string;
  model: string;
  name: string | null;
  type: string;
}

export interface Citation {
  chunk_id: string;
  page: number;
}

export interface AskResponse {
  query_id: string;
  question: string;
  answer: string;
  intent: string | null;
  citations: Citation[];
  grounded: boolean;
  escalated: boolean;
}

// fetch does not throw on 404 or 500 - it only rejects if the network fails.
// Checking response.ok is what turns an error status into an actual error.
async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`${response.status} ${response.statusText}: ${detail}`);
  }

  return response.json() as Promise<T>;
}

export function listProducts(): Promise<Product[]> {
  return request<Product[]>("/products");
}

export function ask(question: string, productId: string): Promise<AskResponse> {
  return request<AskResponse>("/ask", {
    method: "POST",
    body: JSON.stringify({ question, product_id: productId }),
  });
}
