import { forwardRef, useId, type InputHTMLAttributes } from "react";

interface Props extends InputHTMLAttributes<HTMLInputElement> {
  etiqueta: string;
  error?: string;
  ayuda?: string;
}

/** Campo de formulario accesible: etiqueta asociada, error anunciado y aria-invalid. */
export const Campo = forwardRef<HTMLInputElement, Props>(function Campo({ etiqueta, error, ayuda, ...resto }, ref) {
  const id = useId();
  const idError = `${id}-error`;
  return (
    <div className="campo">
      <label htmlFor={id}>{etiqueta}</label>
      <input
        id={id}
        ref={ref}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? idError : undefined}
        {...resto}
      />
      {ayuda && !error && <span className="ayuda">{ayuda}</span>}
      {error && (
        <span id={idError} className="error" role="alert">
          {error}
        </span>
      )}
    </div>
  );
});
