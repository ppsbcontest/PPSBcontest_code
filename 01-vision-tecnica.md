# 01 — Visión Técnica

> **Versión**: 1.1
> **Fecha**: 11 de mayo de 2026
> **Estado**: Refinado durante construcción del MVP. Ver `02-arquitectura.md` para estado de implementación.

---

## Resumen ejecutivo

**Rutiva** es una capa de developer-experience construida sobre el Open Banking de Bancaribe, diseñada para captar el segmento SMB (pequeñas y medianas empresas) del e-commerce venezolano — un mercado actualmente desatendido por las pasarelas existentes (Megasoft, Cashea, UbiiAPI, Yipi, Cujiware) que se enfocan en enterprise, modelos de financiamiento o plugins fragmentados.

Nuestra propuesta no compite con Bancaribe — **opera encima de Bancaribe** como capa de abstracción developer-friendly, replicando la filosofía que hizo a Stripe el líder global de procesamiento de pagos.

---

## El problema

### Lado del banco

Bancaribe ha invertido significativamente en infraestructura de Open Banking. Su portafolio público incluye 8 APIs (C2P2, B2P, Transferencia Inmediata, ConsultaSaldo, MovimientoCuentas, ConsultaCuentas, ConsultarOperaciones, BancaribeBCV, ValidacionServicios) que técnicamente igualan a cualquier pasarela global.

Sin embargo, la adopción en el segmento SMB es limitada por barreras de developer-experience, no técnicas:

- **Documentación detrás de login**: imposible evaluar antes de comprometerse.
- **Sandbox no público**: requiere proceso manual de habilitación.
- **SDKs solo en Java/Android**: anticuado para el desarrollador web/JavaScript moderno.
- **Onboarding manual**: vía email (`mdpagos@bancaribe.com.ve`), sin self-service.
- **Sin plugins listos**: WooCommerce, Shopify, PrestaShop requieren integración custom.
- **Costos opacos**: información de tarifas no pública.

### Lado del mercado

Las pasarelas existentes en Venezuela cubren segmentos distintos al SMB:

| Pasarela | Segmento real | Gap |
|---|---|---|
| **Megasoft** | Enterprise (cadenas, aerolíneas) | No SMB |
| **Cashea** | BNPL, no procesamiento puro | Modelo distinto |
| **UbiiAPI** | Mobile-first / billetera Ubii | Cerrado al ecosistema propio |
| **Yipi** | Plugins WooCommerce | Solo CMS, sin SDK propio |
| **Cujiware** | Casa de software (no procesador) | No es pasarela como tal |

**Resultado**: el e-commerce SMB venezolano (decenas de miles de tiendas) o no procesa pagos digitales o usa soluciones manuales (transferencias verificadas a mano, screenshots de Pago Móvil P2P). Existe una oportunidad clara para el primer producto developer-first de pagos en Venezuela.

---

## Nuestra solución

Rutiva construye lo que falta entre el desarrollador y el Open Banking de Bancaribe:

### 1. SDK moderno
TypeScript/JavaScript, Python y PHP. Una sola línea de instalación (`npm install @rutiva/sdk`), API tipada, ejemplos copy-paste, errores legibles.

```javascript
// Aceptar pagos C2P en Venezuela en 5 líneas
import { Rutiva } from '@rutiva/sdk';
const rutiva = new Rutiva('sk_test_...');
const payment = await rutiva.payments.create({
  amount: 50.00,
  currency: 'VES',
  customer: { phone: '04141234567', id: 'V12345678' }
});
```

### 2. Dashboard self-service
Registro en 2 minutos, generación instantánea de API keys de prueba, sandbox sin solicitudes por email, métricas en tiempo real, configuración de webhooks vía UI.

### 3. Checkout widget embebible
Una etiqueta `<script>` y un botón. Modal pre-construido con el flujo C2P completo (datos del cliente, solicitud de OTP, confirmación). Diseño moderno, accesible, móvil-first.

### 4. Plugins listos para CMS
WooCommerce, Shopify, PrestaShop, Magento. Instalación de un clic. Configuración con la API key.

### 5. Documentación pública estilo Stripe
`docs.rutiva.dev` con quickstart, API reference, ejemplos en múltiples lenguajes, sandbox en línea, troubleshooting.

---

## Diferenciador estratégico

### Vs. otros postulantes a Shark Bank
La mayoría llegará pidiendo "permítannos usar su API". Nosotros llegamos con investigación específica del Open Banking actual de Bancaribe, identificación concreta de gaps de DX, y una propuesta que **multiplica la adopción de la infraestructura existente del banco** en lugar de pedir nueva infraestructura.

### Vs. pasarelas existentes
Somos la única propuesta que ataca el segmento SMB con producto integrado developer-first. Megasoft y otros tienen API y procesan pagos, pero ninguno construye la experiencia completa que un desarrollador moderno espera (sandbox público, docs accesibles, SDK en lenguajes modernos, dashboard self-service).

---

## Modelo operativo y regulatorio

### Fase 1 (Mes 0-12, post-concurso): Facilitador puro

Operamos como **pasarela tecnológica** sin manejar fondos directamente. El dinero fluye directo del cliente al comerciante a través de la infraestructura interbancaria de Bancaribe (Conexus). Nuestra empresa orquesta la transacción tecnológicamente y emite confirmaciones.

**Implicaciones regulatorias**:
- No requiere licencia IPSP propia ante Sudeban
- No requiere capital regulatorio de agregador
- Operación inmediata bajo el marco existente
- Compliance KYC/AML básico de comerciantes (no de transacciones)

**Limitación aceptada**: comerciantes deben tener cuenta jurídica en Bancaribe. **Convertimos esta limitación en propuesta de valor**: cada comerciante onboardeado por nuestra plataforma es un nuevo cliente jurídico de Bancaribe — funcionamos como canal de adquisición de cuentas con costo cercano a cero para el banco.

**Modelo de monetización Fase 1**: revenue share preferencial con Bancaribe, según el modelo del concurso (hasta 50% de comisiones netas durante el primer año).

### Fase 2 (Mes 12-24): Expansión multi-banco

Integración con BNC, Mercantil, BVC, otros. Mismo Bank Adapter Pattern arquitectónico. Bancaribe mantiene posición de **founding partner** con condiciones preferenciales.

**Mercado**: cualquier comerciante venezolano con cuenta en cualquier banco soportado.

**Modelo de monetización Fase 2**: híbrido — revenue share del banco adquirente + suscripción SaaS por features avanzadas (analytics, anti-fraude, plugins premium).

### Fase 3 (Mes 24+): Agregador apadrinado por Bancaribe

Bajo el paraguas regulatorio de Bancaribe como **sub-agente tecnológico** (corresponsalía no bancaria), evolucionamos a manejo directo de fondos. Esto requiere:

- Contrato de sub-agencia con Bancaribe
- Cuenta operativa apadrinada
- Sistema KYC/AML real con software de compliance
- Bond/garantía según negociación

**Habilita productos avanzados**:
- Split payments para marketplaces (modelo Stripe Connect)
- Escrow / holds para pagos condicionados
- Refunds instantáneos desde balance propio
- **Financiamiento a comerciantes basado en flujo transaccional (modelo Stripe Capital)**
- Multi-divisa (VES, USD, USDT)

**Modelo de monetización Fase 3**: comisión completa al comerciante (1.5%-2.5%) + float income + productos premium.

**Posicionamiento estratégico**: Bancaribe se convierte en el proveedor regulatorio principal del fintech privado más grande de Venezuela.

---

## Arquitectura técnica preparada para evolución

El MVP construye la Fase 1 con un Bank Adapter Pattern (Strategy) que permite agregar bancos adicionales (Fase 2) sin tocar el core. Las interfaces del adapter ya contemplan modos `facilitator` y `aggregator` para Fase 3 — la implementación del modo agregador queda pendiente del acuerdo de sub-agencia con Bancaribe.

```python
class BankAdapter(ABC):
    """Soporta modo Facilitator (Fase 1) y Aggregator (Fase 3)."""
    
    @abstractmethod
    async def initiate_c2p_to_merchant(self, ...):
        """Liquidación directa al comerciante (Fase 1)."""
        pass
    
    @abstractmethod
    async def initiate_c2p_to_aggregator_account(self, ...):
        """Liquidación a cuenta agregadora (Fase 3, requiere sub-agencia)."""
        raise NotImplementedError("Aggregator mode requires Bancaribe sponsorship contract")
```

---

## Por qué Bancaribe

- **Trayectoria de innovación**: 4 premios Fintech Américas (2021 Plata, 2022 Platino, 2023 Oro, 2024 Platino, 2025 Platino).
- **Open Banking ya construido**: 8 APIs robustas listas para consumir.
- **Apetito explícito por integraciones**: Shark Bank establece como objetivo "atraer startups del ecosistema venezolano para conectarlos con la infraestructura bancaria del banco".
- **Match cultural**: nuestra mentalidad developer-first complementa la inversión tecnológica del banco.

---

## Por qué nosotros

- **Equipo técnico-comercial complementario**: ingeniería + diseño/negocio.
- **Investigación profunda y específica**: identificamos APIs concretas, gaps específicos, y caminos regulatorios viables — no propuestas genéricas.
- **Visión de tres fases**: arrancamos modesto y honesto (Fase 1) pero apuntamos a algo grande (Modelo C). El concurso es exactamente el catalizador que conecta los dos puntos.
- **Empresa legalmente constituida**: cumplimos requisitos formales del concurso desde el día uno.

---

## Métricas de éxito propuestas

### Fase 1 — Piloto post-concurso (Mes 0-3)
- 5-10 comerciantes onboardeados
- 100+ transacciones procesadas
- Tasa de aprobación >95%
- NPS de comerciantes >40

### Fase 1 — Crecimiento (Mes 3-12)
- 100+ comerciantes activos
- $500K+ USD/mes procesados
- Tasa de aprobación >97%
- 2 plugins CMS publicados (WooCommerce + Shopify)

### Fase 2 — Multi-banco (Mes 12-24)
- 4+ bancos integrados
- 500+ comerciantes
- $5M+ USD/mes procesados
- Bancaribe mantiene >40% del volumen total

---

## Riesgos identificados y mitigaciones

| Riesgo | Mitigación |
|---|---|
| **Cambios regulatorios Sudeban/BCV** | Operar bajo paraguas Bancaribe en todas las fases; evolución a Modelo C requiere apadrinamiento explícito del banco. |
| **Fraude / chargebacks** | Fase 1: el banco asume el riesgo. Fase 3: implementación de anti-fraude propio + cobertura por bond/seguro. |
| **Concentración en un solo banco** | Fase 2 introduce multi-banco arquitectónicamente desde día 1. |
| **Competencia de bancos haciendo su propia capa DX** | Costo de switching alto: comerciantes onboardeados con plugins y SDK no migran fácil. Construimos network effects vía marketplace. |
| **Adopción lenta del SMB venezolano** | Estrategia inicial focalizada en e-commerces ya digitalizados (WooCommerce existente, Instagram Shopping); marketing técnico vía contenido developer. |

---

## Próximos pasos

- **Mayo 2026**: Aplicación a Shark Bank Bancaribe con MVP funcional.
- **Junio-Julio 2026**: Demo Day, negociación de piloto.
- **Agosto-Octubre 2026**: Piloto comercial con 5-10 comerciantes seleccionados.
- **Noviembre 2026 - Mayo 2027**: Crecimiento Fase 1, preparación de Fase 2.
- **Mes 12+**: Inicio de conversaciones formales para sub-agencia (Modelo C).
