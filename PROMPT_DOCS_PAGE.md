# Prompt: Agregar página de documentación técnica al landing de Rutiva

> **Cómo usar este prompt**: cópialo y pégalo en tu agente de código (Claude Code / Cursor / etc.) abierto en el repo del landing. Está pensado para una sola pasada de implementación. Si el agente pregunta antes de empezar, pídele que primero te muestre un plan corto y luego ejecute.

---

## Contexto del proyecto destino

Tengo un landing ya en producción construido con:

- **React + TypeScript**
- **Vite**
- **TanStack Start** (SSR)
- Estilos, componentes y paleta ya definidos en el repo (NO inventar nuevos; reusar lo existente).

Quiero agregarle una **nueva sección de documentación técnica pública** que sirva para que developers integren la API de **Rutiva** (pasarela de pagos C2P para Venezuela).

La fuente de verdad del contenido es el archivo `DOCS_LANDING_CONTENT.md` que te paso adjunto (o referencia el repo backend). El contenido debe transformarse a páginas web navegables, **no embeber el markdown crudo en un `<div>`**.

---

## Objetivo

Replicar la **experiencia de navegación y lectura de la documentación pública de React Native** (https://reactnative.dev/docs/getting-started), **manteniendo el estilo visual y la estructura de mi landing actual**.

No quiero que la docs se vea como un sitio externo pegado. Debe sentirse parte del producto: misma tipografía, mismos colores, mismos componentes base (botones, links, cards), mismo header/footer del landing.

---

## Requerimientos funcionales

### 1. Estructura de rutas (TanStack Router)

Crear nueva sección bajo `/docs`:

```
/docs                            → redirige a /docs/introduccion
/docs/introduccion               → conceptos clave + diagrama de flujo
/docs/autenticacion              → API keys, ambientes
/docs/bancos                     → GET /v1/banks
/docs/crear-pago                 → POST /v1/payments (backend)
/docs/confirmar-pago             → POST /v1/payments/{id}/confirm (frontend con client_secret)
/docs/cancelar-pago              → POST /v1/payments/{id}/cancel
/docs/consultar-pago             → GET detalle + listado paginado
/docs/webhooks                   → registrar endpoint, verificar firma HMAC
/docs/errores                    → tabla de códigos HTTP
/docs/buenas-practicas           → checklist final
```

Cada ruta es una página independiente con su propio archivo `.tsx`. Aprovechar el routing por archivos de TanStack Start.

### 2. Layout `/docs/*` (estilo React Native)

Cada página dentro de `/docs/*` comparte un layout común:

```
┌───────────────────────────────────────────────────────────────────────┐
│  Header global del landing (sin cambios)                              │
├──────────────┬─────────────────────────────────────┬──────────────────┤
│              │                                     │                  │
│  SIDEBAR     │  CONTENIDO PRINCIPAL                │  TOC LATERAL     │
│  (nav docs)  │  (markdown renderizado)             │  (anclas H2/H3)  │
│              │                                     │                  │
│  - categorías│  # Título de la página              │  En esta página  │
│  - colapsable│  Texto...                           │  - Sección 1     │
│  - activo    │  ## Sección                         │  - Sección 2     │
│    resaltado │  ```ts                              │                  │
│              │  código con syntax highlight        │                  │
│              │  ```                                │                  │
│              │                                     │                  │
│              │  [← Anterior]      [Siguiente →]    │                  │
│              │                                     │                  │
├──────────────┴─────────────────────────────────────┴──────────────────┤
│  Footer del landing (sin cambios)                                     │
└───────────────────────────────────────────────────────────────────────┘
```

**Reglas del layout:**

- Sidebar **sticky** en desktop (≥ `lg` breakpoint), colapsable a drawer en mobile (botón hamburguesa).
- Sidebar muestra todas las páginas agrupadas por categorías (`Introducción`, `Endpoints`, `Webhooks`, `Referencia`). La página activa queda resaltada.
- TOC lateral derecho **solo en desktop ≥ `xl`**. Lista de `<h2>` y `<h3>` de la página actual; cada item es un ancla; el ítem visible se highlightea al scrollear (intersection observer).
- Navegación previa/siguiente abajo del contenido principal, basada en el orden del sidebar.
- Barra de búsqueda en el tope del sidebar (cliente, fuzzy match contra los títulos/keywords de las páginas; **no implementar Algolia ahora**, solo búsqueda local in-memory).
- Cada `<h2>` y `<h3>` tiene un anchor `#` clickeable que copia el link al portapapeles (estilo GitHub/React docs).
- Breadcrumb arriba del título: `Docs / Categoría / Página actual`.

### 3. Renderizado de contenido

**No usar `dangerouslySetInnerHTML` con markdown crudo.** Cada página debe estar escrita en JSX usando **componentes reutilizables de documentación** que vas a crear:

```tsx
<DocPage title="Crear pago">
  <DocIntro>Lorem ipsum...</DocIntro>

  <DocSection id="endpoint">
    <h2>Endpoint</h2>
    <p>...</p>
    <CodeBlock language="bash">{`curl -X POST https://...`}</CodeBlock>
  </DocSection>

  <DocCallout type="warning">
    El <code>client_secret</code> se devuelve UNA SOLA VEZ.
  </DocCallout>

  <CodeTabs>
    <CodeTab label="Node.js" language="ts">{nodeExample}</CodeTab>
    <CodeTab label="Python" language="python">{pyExample}</CodeTab>
    <CodeTab label="cURL" language="bash">{curlExample}</CodeTab>
  </CodeTabs>

  <DocTable
    headers={["Campo", "Tipo", "Validación"]}
    rows={[
      ["amount", "int", "Céntimos. ≥ 1, ≤ 100_000_000_000"],
    ]}
  />
</DocPage>
```

**Componentes a crear (mínimos):**

| Componente | Propósito |
|---|---|
| `DocLayout` | Wrapper con sidebar + TOC + contenido. Usado por el layout route `/docs/_layout.tsx`. |
| `DocSidebar` | Navegación. Recibe el árbol de categorías. Resalta el activo. Colapsable mobile. |
| `DocTOC` | Lista de anclas de la página actual. Se genera desde el DOM o desde props explícitas (preferible props). |
| `DocPage` | Wrapper de página. Renderiza breadcrumb + título + slot de contenido + nav prev/next. |
| `DocSection` | `<section id={id}>` con scroll-margin para que el ancla no quede oculta bajo el header sticky. |
| `DocIntro` | Párrafo lead destacado (tamaño > body, color secundario). |
| `DocCallout` | Caja con borde + icono. Props: `type: "info" \| "warning" \| "tip" \| "danger"`. |
| `CodeBlock` | Bloque de código con syntax highlight + botón "copiar". Soporta `language` prop. |
| `CodeTabs` / `CodeTab` | Tabs para mostrar el mismo snippet en varios lenguajes. Selección persistente por sesión (`localStorage`). |
| `DocTable` | Tabla responsive, scroll horizontal en mobile. |
| `InlineCode` | `<code>` inline con estilo monoespaciado + fondo sutil. |
| `EndpointBadge` | Etiqueta colorizada para método HTTP: `GET` (verde), `POST` (azul), `DELETE` (rojo), etc. |

### 4. Syntax highlighting

Usar **Shiki** (preferido por SSR-friendly, sin runtime JS pesado) o **Prism** si Shiki no encaja con TanStack Start.

- Lenguajes mínimos: `bash`, `json`, `typescript`, `javascript`, `python`, `tsx`.
- Tema: que combine con el del landing. Si el landing tiene dark mode, soportar dark+light.
- Highlight ocurre **build-time / SSR**, no client-side, para evitar flash y mejorar performance.

### 5. Estilos

- **Reusar el sistema de diseño existente del landing.** No traer Tailwind/UI kit nuevo si ya hay uno.
- Tipografía: misma del landing. El cuerpo del contenido usa una escala tipográfica clara (h1 grande, h2 con borde inferior sutil, h3 sin borde, body legible ≥ 16px, line-height ≥ 1.6).
- Colores: usar los tokens/CSS vars del landing. Para el callout, usar variantes semánticas (success/warning/danger/info) ya existentes; si no existen, agregarlas a la paleta del landing de forma minimal.
- Espaciado vertical generoso entre secciones (al estilo React Native: ~32-48px entre `<h2>`).
- Links inline: subrayado en hover, color de marca.
- Mobile-first: layout colapsa a una sola columna en `< lg`. Sidebar se convierte en drawer.

### 6. SSR + SEO

Aprovechar TanStack Start SSR:

- Cada página de docs es server-rendered con su `<title>`, `<meta name="description">`, y `<link rel="canonical">`.
- Sitemap incluye todas las rutas `/docs/*`.
- Open Graph: imagen genérica del landing + título de la página.
- Estructura semántica: `<main>`, `<article>`, `<aside>`, `<nav>`, headings jerárquicos correctos (un solo `<h1>` por página).
- `hreflang` en español por ahora; preparado para multilenguaje pero no traducir aún.

### 7. Accesibilidad

- Focus visible en todos los elementos interactivos.
- Skip link "Saltar al contenido" al inicio del layout.
- Aria-labels en sidebar nav, TOC, botón copiar código, drawer mobile.
- Contraste mínimo AA en todos los textos.
- Sidebar y drawer cierran con `Esc`.
- Code blocks tienen `aria-label` describiendo el lenguaje.

### 8. Performance

- Code splitting por ruta (TanStack Start lo da casi gratis).
- Imágenes (si hay diagramas) en `next-gen` formats (AVIF/WebP) + `loading="lazy"`.
- No cargar Shiki en el cliente si el highlight es SSR.
- Lighthouse target: Performance ≥ 90, Accessibility = 100, SEO ≥ 95.

---

## Contenido de cada página

Las páginas se nutren de `DOCS_LANDING_CONTENT.md` (te lo paso aparte). Adapta el contenido a la división de rutas listada en la sección 1. El archivo de contenido **ya viene mapeado 1:1 a las rutas** — cada sección tiene su slug y título.

Cada página debe terminar con un `DocCallout type="tip"` enlazando a la siguiente sección lógica del sidebar.

---

## Detalles UI tipo React Native docs

Características específicas a replicar:

1. **Sidebar con categorías colapsables**: cada categoría tiene un chevron, se expande/colapsa, estado persiste en `localStorage`.
2. **TOC con highlight progresivo**: el item activo cambia conforme el usuario scrollea, animación suave.
3. **Anchor links autogenerados** en H2/H3, ícono `#` aparece en hover del heading.
4. **Botón "Edit this page"** abajo del contenido, que linkee al archivo fuente en GitHub (opcional, configurable por env var `VITE_DOCS_REPO_URL`).
5. **Versión de la API** mostrada cerca del título principal: `v0.1.0` (leer de `package.json` o de una constante).
6. **Búsqueda** en el sidebar: input que filtra páginas en vivo. Atajo `/` para enfocarlo.
7. **Atajo de teclado** `?` que muestra un modal con los atajos disponibles.
8. **Tabla de contenidos compacta en mobile**: al inicio de cada página, un `<details>` con la lista de secciones, colapsado por defecto.

---

## Entregables esperados

1. **Estructura de archivos** propuesta (ruta `src/routes/docs/...`, componentes en `src/components/docs/...`).
2. **Implementación funcional** de todas las rutas listadas con contenido placeholder o real, lo que sea factible en una pasada.
3. **Componentes de documentación** (lista mínima de la sección 3).
4. **Integración con el sistema de diseño existente** — sin romper el landing actual.
5. **README corto** dentro de `src/components/docs/README.md` explicando cómo agregar una nueva página de docs (estructura del archivo, cómo registrarla en el sidebar, cómo escribir secciones).

---

## Antes de empezar, hacer estas verificaciones

Antes de generar código, **léete primero**:

- `package.json` — para conocer las versiones exactas de React, TanStack Start, Vite, y qué librerías de UI ya hay.
- El layout root actual (`src/routes/__root.tsx` o equivalente) — para entender cómo se compone el header/footer global.
- Cualquier carpeta `src/components/` — para inventariar componentes reutilizables (Button, Container, etc.).
- Tokens de diseño: archivo de colores, `tailwind.config` si existe, `theme.ts`, CSS vars en `:root`, etc.

Si algún componente clave (Button, Link, Container) ya existe en el landing, **úsalo en lugar de crear uno nuevo**.

Si Tailwind ya está configurado en el landing, usa Tailwind. Si usan CSS Modules, mantén CSS Modules. Si usan styled-components, usa styled-components. **No cambies el stack de estilos.**

---

## Restricciones

- ❌ No introducir un nuevo framework de docs (MDX runtime engines como Docusaurus, Astro Starlight, Nextra). Esto debe ser código React nativo en el landing existente.
- ❌ No agregar `MDX` como dependencia si el contenido se puede modelar con los componentes de la sección 3. (Si el equipo decide después que MDX vale la pena, queda como mejora futura.)
- ❌ No reemplazar el sistema de routing del landing — usa TanStack Router como ya está configurado.
- ❌ No copiar literalmente los estilos de react.dev / reactnative.dev (color verde, etc.). Replica el **patrón estructural**, no la marca visual.
- ❌ No commitear `node_modules`, archivos `.env`, ni claves reales.

---

## Plan que espero del agente antes de codear

1. Resumen de cómo está organizado el landing actual (en 5 bullets).
2. Lista de archivos a crear/modificar.
3. Lista de dependencias nuevas (idealmente cero o solo Shiki).
4. Una breve confirmación de que la paleta/tipografía del landing se preservan.

Después de mi OK, ejecutar la implementación completa.

---

## Resultado deseado

Una sección `/docs` que un desarrollador externo abra y sienta que está leyendo documentación profesional comparable a la de React Native, Stripe o Vercel — pero claramente parte del producto Rutiva. Navegación fluida, código copiable, búsqueda instantánea, oscura/clara consistente con el landing, y carga rápida en SSR.
