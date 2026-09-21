import { useState } from "react";

import {
  PRODUCT_TYPES,
  uploadManual,
  type ManualUpload,
  type ProductType,
} from "./api";

const TYPE_LABELS: Record<ProductType, string> = {
  washing_machine: "Washing machine",
  dishwasher: "Dishwasher",
  air_conditioner: "Air conditioner",
  oven: "Oven",
  fridge: "Fridge",
  tv: "TV",
  other: "Other",
};

interface Props {
  // Open state lives in the parent: the ingestion card needs to know whether
  // this form is covering it.
  open: boolean;
  onOpenChange: (open: boolean) => void;
  // Lets the parent refresh the product list once a manual lands, so the new
  // appliance appears in the picker without a reload. The manual travels with
  // it because ingestion has only just started: its id is what the developer
  // panel follows while the worker processes the file.
  onUploaded: (manual: ManualUpload) => void;
}

export default function UploadPanel({ open, onOpenChange, onUploaded }: Props) {
  const [brand, setBrand] = useState("");
  const [model, setModel] = useState("");
  const [type, setType] = useState<ProductType>("other");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!brand.trim() || !model.trim() || !file || busy) return;

    setBusy(true);
    setMessage(null);

    try {
      const manual = await uploadManual(brand.trim(), model.trim(), type, file);
      // Ingestion runs in the background, so the useful thing to report is that
      // it was accepted - not that it is ready, because it is not yet.
      setMessage(`"${manual.title}" received. Processing in the background…`);
      setBrand("");
      setModel("");
      setFile(null);
      onUploaded(manual);
    } catch {
      setMessage("Could not upload the manual. Check that it is a PDF.");
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <button type="button" className="button" onClick={() => onOpenChange(true)}>
        Upload a manual
      </button>
    );
  }

  return (
    <form className="upload" onSubmit={handleSubmit}>
      <div className="upload-head">
        <h2>Upload a manual</h2>
        <button type="button" className="link" onClick={() => onOpenChange(false)}>
          Close
        </button>
      </div>

      <div className="fields">
        <label>
          Brand
          <input
            value={brand}
            onChange={(event) => setBrand(event.target.value)}
            placeholder="Balay"
          />
        </label>

        <label>
          Model
          <input
            value={model}
            onChange={(event) => setModel(event.target.value)}
            placeholder="3TS976BE"
          />
        </label>

        <label>
          Type
          <select
            value={type}
            onChange={(event) => setType(event.target.value as ProductType)}
          >
            {PRODUCT_TYPES.map((value) => (
              <option key={value} value={value}>
                {TYPE_LABELS[value]}
              </option>
            ))}
          </select>
        </label>
      </div>

      <label className="file">
        <input
          type="file"
          accept="application/pdf"
          onChange={(event) => setFile(event.target.files?.[0] ?? null)}
        />
        <span>{file ? file.name : "Choose the manual PDF"}</span>
      </label>

      <button
        type="submit"
        className="button primary"
        disabled={!brand || !model || !file || busy}
      >
        {busy ? "Uploading…" : "Upload"}
      </button>

      {message && <p className="upload-message">{message}</p>}
    </form>
  );
}
