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

export interface ManualUpload {
  id: string;
  title: string;
  source: string;
  status: string;
  page_count: number | null;
  chunk_count: number | null;
  error: string | null;
}

// The categories the backend accepts, mirroring ProductType. Kept as a const
// array so the values and the union type cannot drift apart.
export const PRODUCT_TYPES = [
  "washing_machine",
  "dishwasher",
  "air_conditioner",
  "oven",
  "fridge",
  "tv",
  "other",
] as const;

export type ProductType = (typeof PRODUCT_TYPES)[number];

// Multipart, not JSON: a PDF cannot travel in a JSON body. The browser sets
// the Content-Type itself, boundary included, so we must not set it here -
// naming it without the boundary is what makes these uploads fail.
export async function uploadManual(
  brand: string,
  model: string,
  productType: ProductType,
  file: File,
): Promise<ManualUpload> {
  const form = new FormData();
  form.append("brand", brand);
  form.append("model", model);
  form.append("product_type", productType);
  form.append("file", file);

  const response = await fetch(`${API_URL}/manuals/upload`, {
    method: "POST",
    body: form,
  });

  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json() as Promise<ManualUpload>;
}
