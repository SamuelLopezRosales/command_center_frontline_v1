import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { Rutas } from "./app/rutas";
import { cargarConfig } from "./shared/config";
import { crearAmplifyAuth } from "./shared/sesion/amplifyAuth";
import { crearAuthLocal } from "./shared/sesion/authLocal";
import { SesionProvider } from "./shared/sesion/SesionProvider";
import "./styles.css";

// El acceso local de desarrollo solo existe con el servidor de Vite y la bandera explícita: en la
// compilación de producción `import.meta.env.DEV` vale `false` y esta rama se descarta entera.
// En cualquier otro caso la configuración de Cognito se lee en tiempo de ejecución (T-139).
async function crearAuth() {
  if (import.meta.env.DEV && import.meta.env.VITE_AUTH_LOCAL === "true") return crearAuthLocal();
  const config = await cargarConfig();
  return crearAmplifyAuth({
    userPoolId: config.userPoolId,
    userPoolClientId: config.userPoolClientId,
    registroAbierto: config.registroAbierto,
  });
}

const cliente = new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } } });
const raiz = document.getElementById("raiz")!;

crearAuth()
  .then((auth) => {
    createRoot(raiz).render(
      <StrictMode>
        <QueryClientProvider client={cliente}>
          <BrowserRouter>
            <SesionProvider auth={auth}>
              <Rutas />
            </SesionProvider>
          </BrowserRouter>
        </QueryClientProvider>
      </StrictMode>,
    );
  })
  .catch(() => {
    raiz.textContent = "No se pudo cargar la configuración de la aplicación. Intenta de nuevo más tarde.";
  });
