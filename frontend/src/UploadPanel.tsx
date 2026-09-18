import { useState } from "react";

import { PRODUCT_TYPES, uploadManual, type ProductType } from "./api";

const TYPE_LABELS: Record<ProductType, string> = {
  washing_machine: "Lavadora",
  dishwasher: "Lavavajillas",
  air_conditioner: "Aire acondicionado",
  oven: "Horno",
  fridge: "Frigorífico",
  tv: "Televisor",
  other: "Otro",
};

interface Props {
  // Lets the parent refresh the product list once a manual lands, so the new
  // appliance appears in the picker without a reload.
  onUploaded: () => void;
}

export default function UploadPanel({ onUploaded }: Props) {
  const [open, setOpen] = useState(false);
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
      setMessage(`"${manual.title}" recibido. Procesando en segundo plano…`);
      setBrand("");
      setModel("");
      setFile(null);
      onUploaded();
    } catch {
      setMessage("No se pudo subir el manual. Comprueba que es un PDF.");
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <button className="link" onClick={() => setOpen(true)}>
        Subir un manual
      </button>
    );
  }

  return (
    <form className="upload" onSubmit={handleSubmit}>
      <div className="upload-head">
        <h2>Subir un manual</h2>
        <button type="button" className="link" onClick={() => setOpen(false)}>
          Cerrar
        </button>
      </div>

      <div className="fields">
        <label>
          Marca
          <input
            value={brand}
            onChange={(event) => setBrand(event.target.value)}
            placeholder="Balay"
          />
        </label>

        <label>
          Modelo
          <input
            value={model}
            onChange={(event) => setModel(event.target.value)}
            placeholder="3TS976BE"
          />
        </label>

        <label>
          Tipo
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
        <span>{file ? file.name : "Selecciona el PDF del manual"}</span>
      </label>

      <button type="submit" disabled={!brand || !model || !file || busy}>
        {busy ? "Subiendo…" : "Subir"}
      </button>

      {message && <p className="upload-message">{message}</p>}
    </form>
  );
}
