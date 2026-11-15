import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { Rutas } from "./app/rutas";
import { crearAmplifyAuth } from "./shared/sesion/amplifyAuth";
import { SesionProvider } from "./shared/sesion/SesionProvider";
import "./styles.css";

const auth = crearAmplifyAuth({
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
