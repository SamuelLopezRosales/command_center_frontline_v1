import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { Rutas } from "./app/rutas";
import { crearAmplifyAuth } from "./shared/sesion/amplifyAuth";
import { crearAuthLocal } from "./shared/sesion/authLocal";
import { SesionProvider } from "./shared/sesion/SesionProvider";
import "./styles.css";

// El acceso local de desarrollo solo existe con el servidor de Vite y la bandera explícita: en la
// compilación de producción `import.meta.env.DEV` vale `false` y esta rama se descarta entera.
const auth =
  import.meta.env.DEV && import.meta.env.VITE_AUTH_LOCAL === "true"
    ? crearAuthLocal()
    : crearAmplifyAuth({
        userPoolId: import.meta.env.VITE_COGNITO_USER_POOL_ID ?? "",
        userPoolClientId: import.meta.env.VITE_COGNITO_CLIENT_ID ?? "",
      });
const cliente = new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } } });

createRoot(document.getElementById("raiz")!).render(
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
