// Comprobación de la propia herramienta: si axe no detectara nada, todas las pruebas de
// accesibilidad pasarían en falso.
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { REGLAS_DESACTIVADAS, esperarAccesible, violacionesGraves } from "./axe";

describe("revisión de accesibilidad con axe", () => {
  it("detecta un botón sin nombre y un campo sin etiqueta", async () => {
    const { container } = render(
      <div>
        <button type="button" />
        <input type="text" />
      </div>,
    );
    const ids = (await violacionesGraves(container)).map((v) => v.id);
    expect(ids).toContain("button-name");
    expect(ids).toContain("label");
    await expect(esperarAccesible(container)).rejects.toThrow(/button-name/);
  });

  it("acepta un marcado correcto", async () => {
    const { container } = render(
      <form>
        <label htmlFor="n">Nombre</label>
        <input id="n" type="text" />
        <button type="submit">Guardar</button>
      </form>,
    );
    await esperarAccesible(container);
  });

  it("solo se desactivan las reglas documentadas", () => {
    expect(REGLAS_DESACTIVADAS).toEqual(["color-contrast", "region", "scrollable-region-focusable"]);
  });
});
