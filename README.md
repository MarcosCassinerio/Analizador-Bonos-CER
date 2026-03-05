# Proyecto: Análisis de Curva de Rendimientos Reales y Valor Relativo en Bonos CER

## Contexto general

Este proyecto analiza el mercado de bonos argentinos ajustados por CER (inflación) desde una perspectiva cuantitativa. El objetivo es construir un sistema que modele la curva de rendimientos reales, detecte valor relativo entre bonos, y detecte anomalías en la estructura de la curva.

El proyecto fue diseñado deliberadamente sobre bonos CER y no sobre acciones argentinas o bonos en USD, por las siguientes razones metodológicas:
- Los bonos CER tienen una lógica más modelable que acciones locales, que están sujetas a shocks exógenos difíciles de capturar (cepos, elecciones, cambios de régimen)
- Los bonos en USD (familia GD) tienen solo 6 puntos para ajustar la curva, lo que hace el ajuste poco robusto
- El universo CER tiene heterogeneidad real en estructura, duration y liquidez, lo que justifica dos grupos bien diferenciados (`lecer` / `cer`) y análisis de valor relativo dentro de cada uno

---

## Universo de bonos

Los bonos se dividen en dos grupos fijos (`lecer` / `cer`) que reflejan diferencias estructurales reales y justifican curvas Nelson-Siegel separadas.

### Bonos incluidos

#### Grupo `lecer` — Letras del Tesoro CER (zero coupon, bullet)
Instrumento de corto plazo: un único pago al vencimiento (capital ajustado por CER, sin cupones). Curva cubre durations ~0.05–1.2 años.

| Ticker | Instrumento | Vencimiento aprox. |
|--------|-------------|-------------------|
| X15Y6  | LECER mayo 2026 | may-26 |
| X29Y6  | LECER mayo 2026 (serie 29) | may-26 |
| X31L6  | LECER julio 2026 | jul-26 |
| X30N6  | LECER nov 2026 | nov-26 |
| TZXA7  | LECER abr 2027 | abr-27 |
| TZXY7  | LECER may 2027 | may-27 |

#### Grupo `cer` — BONCERs del Tesoro y soberanos reestructurados
Bonos con cupones periódicos y/o amortizaciones. Curva cubre durations ~0.07–9.5 años.

| Ticker | Instrumento | Estructura |
|--------|-------------|------------|
| TZXM6  | BONCER mar 2026 | Bullet, cupón semestral |
| TZXO6  | BONCER oct 2026 | Bullet, cupón semestral |
| TZXD6  | BONCER dic 2026 | Bullet, cupón semestral |
| TZX26  | BONCER 2026 | Bullet, cupón semestral |
| TX26   | BONCER TX26 | Amortización en cuotas, cupón semestral |
| TZXM7  | BONCER mar 2027 | Bullet, cupón semestral |
| TZX27  | BONCER 2027 | Bullet, cupón semestral |
| TZXD7  | BONCER dic 2027 | Bullet, cupón semestral |
| TZX28  | BONCER 2028 | Bullet, cupón semestral |
| TX28   | BONCER TX28 | Amortización en cuotas, cupón semestral |
| TX31   | BONCER TX31 | Amortización en cuotas, cupón semestral |
| DICP   | DISCOUNT CER Ley Argentina | Amortización compleja, canje 2005 |
| DIP0   | DISCOUNT CER Ley Externa | Igual a DICP, distinta legislación |
| PARP   | PAR CER Ley Argentina | Amortización compleja, canje 2005 |
| PAP0   | PAR CER Ley Externa | Igual a PARP, distinta legislación |
| CUAP   | CUASI PAR CER | Amortización compleja, canje 2005 |

**Notas:**
- La separación `lecer`/`cer` es estructural: los LECER son zero coupon y su curva requiere λ calibrado en un rango corto; los CER tienen flujos intermedios y cubren todo el espectro de durations.
- DICP/DIP0 y PARP/PAP0 son económicamente el mismo bono con distinta legislación (Ley Argentina vs Nueva York). Se incluyen ambas series para capturar el spread de legislación.
- Los tickers LECER rotan a medida que vencen y el Tesoro emite nuevas series. La tabla refleja el universo vigente; se actualiza a medida que entran nuevos instrumentos.

---

### Bonos explícitamente excluidos

| Ticker / Clase | Razón de exclusión |
|---|---|
| **TX30** | Ya no opera en el mercado secundario (fue canjeado o venció sin reemplazante líquido) |
| **Bonos provinciales CER** (ej. PBA, Córdoba) | Riesgo de crédito distinto al soberano; rompe la homogeneidad del emisor necesaria para modelar una única curva |
| **Bonos en USD (familia GD/AL)** | Solo 6 puntos en la curva; insuficiente para ajustar Nelson-Siegel de forma robusta |
| **Bonos dollar-linked (TV series)** | Distinto activo subyacente (tipo de cambio); no son comparables con CER |
| **LECAP** (letras capitalizables) | Ajustan por tasa fija, no por CER; instrumento diferente |
| **Bonos CER sub-soberanos o corporativos** | Riesgo de crédito heterogéneo; fuera del alcance del modelo |
| **LECERs ya vencidas** | No tienen precios de mercado; no aportan al análisis vigente |

---

## Stack tecnológico

| Herramienta | Uso |
|---|---|
| Python | Lenguaje principal |
| pandas | Manipulación de datos |
| numpy | Operaciones numéricas |
| scipy.optimize | Cálculo de YTM, ajuste Nelson-Siegel |
| scikit-learn | Clustering, PCA |
| PyTorch | Autoencoder para detección de anomalías |
| PostgreSQL | Base de datos (nombre: `bonos_ar`) |
| SQLAlchemy 2.0 | ORM con `DeclarativeBase` |
| Alembic | Migraciones de base de datos |
| Pydantic v2 | Schemas de validación de datos |
| Requests | Cliente HTTP para APIs externas |
| python-dotenv | Gestión de variables de entorno |
| MLflow | Tracking de experimentos y parámetros |
| Jupyter Notebooks | Exploración y análisis |
| matplotlib / seaborn | Visualización |

---

## Conceptos clave del dominio

### YTM (Yield to Maturity)
Tasa interna de retorno implícita en el precio de mercado de un bono, considerando todos los flujos de caja futuros (cupones + amortizaciones). Se calcula numéricamente resolviendo la TIR con `scipy.optimize`. Para bonos CER los flujos están ajustados por inflación, lo que requiere proyectar el coeficiente CER futuro.

### Duration modificada
Mide la sensibilidad del precio del bono a cambios en la tasa real. Dos bonos con el mismo vencimiento nominal pueden tener durations muy distintas si tienen estructuras de amortización diferentes. Es el eje x natural de la curva.

### Coeficiente CER
Índice que sigue la inflación (atado al IPC con rezago de días). El capital y cupones de los bonos CER se ajustan por este coeficiente. Para proyectar flujos futuros se usa inflación implícita de mercado (diferencial entre bonos CER y nominales de similar plazo) o el REM del BCRA.

### Curva Nelson-Siegel
Modelo matemático que ajusta una función continua sobre los puntos (plazo, yield). La fórmula es:

```
y(t) = β0 + β1 * (1 - e^(-t/λ)) / (t/λ) + β2 * [(1 - e^(-t/λ)) / (t/λ) - e^(-t/λ)]
```

Los parámetros tienen interpretación económica:
- **β0**: nivel general de tasas (largo plazo)
- **β1**: pendiente de la curva (corto vs largo). Si es negativo la curva es creciente, si es positivo es invertida
- **β2**: curvatura (joroba en plazos medios)
- **λ**: parámetro de escala temporal

Se ajusta minimizando el error cuadrático entre yields observados y yields teóricos (regresión no lineal de mínimos cuadrados con `scipy.optimize.curve_fit`), ponderando por liquidez de cada bono.

### Valor relativo y residuales
Una vez ajustada la curva, para cada bono se calcula:

```
residual = yield_observado - yield_curva(duration_del_bono)
```

La serie histórica de residuales se normaliza en z-score:

```
z = (residual_hoy - media_historica) / desvio_historico
```

- z > 1.5 o 2: bono inusualmente barato relativo a la curva
- z < -1.5: bono inusualmente caro

### Estructura de tres niveles de análisis
1. **Intragrupo**: residuales NS por bono dentro de `lecer` o `cer` (z-score: ¿está rich/cheap respecto a su curva?)
2. **Intergrupo**: spread entre curvas `lecer` y `cer` en durations comparables (prima por tipo de instrumento)
3. **Global**: anomalía multidimensional detectada por el autoencoder sobre el vector de features completo

---

## Pipeline y notebooks

### ETL (src/etl.py)
Fuentes de datos:
- **Rava**: precios OHLCV diarios por bono (POST a API pública, sin autenticación)
- **Docta Capital**: flujos de caja por bono (API con Bearer token, `client_id` + `client_secret`)
- **BCRA**: coeficiente CER diario (API v4.0, variable id=30, sin autenticación)

Tablas en PostgreSQL:
- `grupos`: grupos de bonos (corto/medio/largo), tabla dinámica con FK desde `bonos`
- `bonos`: universo de bonos activos con metadata estática (ticker, nombre, grupo, tipo, vencimiento)
- `cashflows`: flujos de caja por bono — **se cargan una única vez** por bono, no se actualizan diariamente
- `precios_raw`: precios OHLCV diarios por bono (apertura, máximo, mínimo, cierre, volumen)
- `coeficientes_cer`: valor del CER por fecha, cargado diariamente desde BCRA
- `metricas_diarias`: TIR, duration modificada, paridad, valor técnico, intereses corridos, valor residual — **calculadas en el mismo momento que se guarda `precios_raw`**, ya que en ese punto se tienen todos los datos necesarios

Las funciones de acceso a las APIs externas están encapsuladas en `src/apis.py` (importado por `etl.py`). El ETL también expone `backfill_metricas()`, que recalcula métricas para precios históricos que no las tienen aún.

### src/pricing.py
- Cálculo de YTM a partir de precio y flujos de caja con `scipy.optimize`
- Cálculo de duration modificada
- Proyección de coeficiente CER futuro

### src/nelson_siegel.py
- Ajuste de curva Nelson-Siegel por grupo y global
- Ponderación por liquidez
- Logging de parámetros y RMSE a MLflow

### src/clustering.py
- Features: duration media, volumen promedio, dispersión de TIR, tipo de amortización
- K-Means y clustering jerárquico
- Validación de la separación `lecer`/`cer` y detección de sub-estructura interna

### src/signals.py
- Cálculo de residuales y z-scores
- Señales intragrupo, intergrupo y globales
- Consolidación de señales de los tres niveles

---

### Notebook 01: EDA general
- Evolución histórica de yields reales por bono
- Distribución de durations y volúmenes
- Correlación con variables macro: inflación mensual, tipo de cambio CCL, tasa BCRA
- Visualización de la curva real en distintas fechas históricas
- Formas inusuales de la curva argentina (invertida en períodos de estrés)

### Notebook 02: Curvas de tasas reales (LECER y CER)
- Visualización de la curva TIR vs Duration a lo largo del tiempo
- Curva LECER: una línea por mes desde el primer dato disponible (~2025-12)
- Curva CER: una línea por trimestre desde el primer dato disponible (~2021-06)
- Identificación de regímenes: pre/post 2025-Q2 (desinflación acelerada vs régimen actual)
- Conclusión: el rango útil para entrenamiento del modelo arranca en 2025-Q2

### Notebook 03: Ajuste Nelson-Siegel ✅
- Ajuste diario del modelo Nelson-Siegel separado por grupo (`lecer` / `cer`)
- Evolución temporal de parámetros β₀, β₁, β₂, λ y RMSE
- Curvas ajustadas vs datos reales (muestra de fechas)
- Residuales por bono: detección de bonos sistemáticamente rich/cheap

### Notebook 04: Clustering
- Construcción de matriz de features por bono: duration media, volumen promedio, tipo amortización, dispersión de TIR
- K-Means y clustering jerárquico sobre el universo completo
- Validación de que la separación `lecer`/`cer` es la partición natural del espacio
- Detección de sub-estructura interna (ej. reestructurados vs BONCERs del Tesoro dentro de `cer`)
- No se derivan grupos corto/mediano/largo: el objetivo es confirmar o enriquecer la clasificación existente

### Notebook 05: PCA sobre parámetros Nelson-Siegel
- PCA sobre la serie histórica de parámetros (β₀, β₁, β₂, λ) de cada grupo
- Modos de movimiento de la curva real:
  - PC1: movimientos paralelos (nivel general de tasas)
  - PC2: rotaciones (cambios de pendiente)
  - PC3: cambios de curvatura
- Interpretación macroeconómica de cada componente
- Construcción del vector de features diario para el autoencoder: parámetros NS + residuales por bono + volúmenes normalizados

### Notebook 06: Autoencoder PyTorch (detección de anomalías)
Ver sección dedicada abajo.

### Notebook 07: Síntesis y señales
- z-scores de residuales NS por bono (señales intragrupo)
- Spread entre grupos `lecer` y `cer` en durations comparables (señal intergrupo)
- Anomalía global según el autoencoder (z_anomalia)
- Dashboard en notebook con estado actual de todas las señales
- Señal más robusta: cuando intragrupo, intergrupo y global apuntan en la misma dirección
- Logging histórico de señales en MLflow

---

## Módulo de detección de anomalías con PyTorch

### Motivación
Un z-score univariado detecta si un bono individual está raro. El autoencoder detecta si la **configuración global de la curva** es inusual, capturando anomalías multidimensionales que los z-scores no ven. Tiene sentido financiero real: un shock de inflación, una intervención del BCRA o una dislocation de precios generan patrones en múltiples bonos simultáneamente.

### Input del autoencoder
Cada día queda representado por un vector de features (construido en NB05):
- Parámetros Nelson-Siegel de cada grupo: β₀, β₁, β₂, λ (×2 grupos = 8 valores)
- Residuales de cada bono respecto a su curva NS del grupo
- Spread entre grupos `lecer` y `cer` en durations comparables
- Volumen operado normalizado por grupo

### Arquitectura
Autoencoder feedforward simple en PyTorch:

```
Encoder: input_dim → 32 → 16 → 8 (espacio latente)
Decoder: 8 → 16 → 32 → input_dim
Activación: ReLU en capas ocultas, lineal en output
Loss: MSE entre input y reconstrucción
```

### Entrenamiento
- Se entrena sobre períodos de mercado "normal" (excluir ventanas con eventos extremos conocidos)
- El autoencoder aprende a comprimir y reconstruir estados normales de la curva
- Días donde el error de reconstrucción es alto = configuración inusual de la curva

### Señal de anomalía
```
error_reconstruccion = MSE(input, output)
z_anomalia = (error_hoy - media_historica_error) / desvio_historico_error
```

Si z_anomalia > 2: anomalía detectada. Se logea en MLflow junto con la fecha y el error.

### Logging con MLflow
- Parámetros del modelo: arquitectura, learning rate, epochs
- Métricas de entrenamiento: loss por epoch
- Serie histórica de errores de reconstrucción
- Fechas de anomalías detectadas con su z-score

---

## Estructura de carpetas

No se usa directorio `data/` — todos los datos crudos y procesados viven en PostgreSQL (`bonos_ar`).

```
analisador-bonos-cer/
├── alembic/                    # migraciones de base de datos
│   ├── versions/               # migraciones versionadas
│   └── env.py
├── notebooks/
│   ├── 01_eda.ipynb
│   ├── 02_curvas_tasas_reales.ipynb
│   ├── 03_clustering.ipynb
│   ├── 04_intragrupo.ipynb
│   ├── 05_curva_completa.ipynb
│   ├── 06_autoencoder_anomalias.ipynb
│   └── 07_señales.ipynb
├── scripts/
│   ├── explorar_apis.py        # exploración de APIs: Rava, Docta, BCRA
│   └── setup_and_run.py        # setup inicial y ejecución del ETL
├── src/
│   ├── db/
│   │   ├── models.py           # modelos SQLAlchemy
│   │   └── session.py          # engine y SessionLocal
│   ├── schemas/
│   │   ├── bono.py             # schemas Pydantic
│   │   ├── cashflow.py
│   │   ├── precio.py
│   │   └── metrica.py
│   ├── enums.py                # enums Python (TipoAmortizacion, TipoCashflow)
│   ├── apis.py                 # acceso a las APIs externas (Rava, Docta, BCRA)
│   ├── etl.py                  # carga diaria de datos
│   ├── pricing.py              # cálculo de TIR, duration, paridad, VT
│   ├── nelson_siegel.py        # ajuste de curva
│   ├── clustering.py
│   └── signals.py              # lógica de valor relativo
├── models/                     # pesos del autoencoder guardados
├── mlflow/                     # experimentos y runs
├── .env                        # variables de entorno (no versionar)
├── .env.example                # plantilla de variables de entorno
├── alembic.ini
├── requirements.txt
└── README.md
```

---

## Decisiones de diseño del ETL

### Fuentes de datos

| Fuente | Datos | Notas |
|--------|-------|-------|
| **Rava** | Precios OHLCV diarios | API pública gratuita, sin autenticación. Cubre historia desde 2005 para bonos largos |
| **Docta Capital** | Cashflows por bono | Requiere `client_id` + `client_secret` (Bearer token). Incluye flujos ajustados por CER |
| **BCRA** | Coeficiente CER diario | API oficial gratuita, sin autenticación. Variable id=30, endpoint v4.0 |

### Fecha de inicio del backfill: 2025-01-01

Se eligió el 1 de enero de 2025 como fecha de inicio de la carga histórica por las siguientes razones:

- **Los LECER en el universo actual (TZXM6, TZXA7, etc.) fueron emitidos en 2024-2025.** Empezar antes implicaría entrenar el autoencoder y ajustar Nelson-Siegel en períodos donde el tramo corto de la curva no existía con estos instrumentos, generando un "estado normal" sesgado.
- **Sin cobertura del tramo corto, β1 (pendiente) de Nelson-Siegel queda mal identificado**, lo que afecta tanto la calidad del ajuste como la detección de anomalías.
- **El autoencoder se diseña sobre parámetros Nelson-Siegel** (β0, β1, β2, λ), no sobre residuales por bono, precisamente para ser robusto a cambios en el universo. Con datos desde 2025 todos los bonos activos están presentes desde el inicio.
- **Un año de historia es suficiente para el arranque**: el modelo se irá recalibrando a medida que acumule datos.

### Lógica de carga diaria y backfill

- El ETL detecta por bono cuál es el `MAX(fecha)` en `precios_raw` y itera desde ahí hasta hoy.
- Se saltean fines de semana y feriados argentinos. Los feriados se consultan en tiempo real desde **Nager.Date** (`GET https://date.nager.at/api/v3/publicholidays/{year}/AR`), sin tabla de feriados en la base de datos.
- Si una fecha no tiene datos (Rava devuelve vacío), se la omite y la próxima ejecución arranca desde el último día exitoso.
- No hay tabla de control de ejecuciones: el propio `MAX(fecha)` en `precios_raw` es el estado.

### Cashflows: carga única por bono

Los cashflows se cargan una sola vez por bono desde Docta y no se actualizan en la carga diaria. Si se detecta un bono nuevo en la tabla `bonos` sin entradas en `cashflows`, el ETL los descarga en ese momento.

### Métricas calculadas al momento de cargar precios

TIR, duration modificada, paridad, valor técnico, intereses corridos y valor residual se calculan en el mismo momento en que se guarda `precios_raw`. En ese punto ya se tienen todos los datos necesarios: precio de cierre (Rava), cashflows (Docta, ya cargados) y CER del día (BCRA). Se guardan en `metricas_diarias` con FK a `precios_raw.id`.

### Diseño de la base de datos

- **`grupos`**: tabla dinámica (no ENUM) para permitir cambios de agrupamiento sin migraciones.
- **`bonos.grupo`**: FK a `grupos.nombre`, no ENUM, porque el universo puede crecer.
- **`tipo_amortizacion`** y **`tipo_cashflow`**: PostgreSQL ENUMs (`tipo_amortizacion_enum`: bullet/cuotas; `tipo_cashflow_enum`: cupon/amortizacion) porque sus valores son fijos por definición del instrumento.
- Migraciones gestionadas con **Alembic**. Una única migración inicial crea todos los objetos (ENUMs primero, luego tablas en orden de dependencias).

---

## Decisiones metodológicas tomadas

- Se usa duration como eje x de la curva (no plazo nominal) para capturar diferencias de amortización
- Los grupos (`lecer`/`cer`) son estructurales: zero coupon vs con cupones. El clustering valida esta separación y detecta sub-estructura interna.
- La curva global se ajusta ponderando por liquidez para que bonos ilíquidos no distorsionen el ajuste
- El autoencoder se entrena solo sobre períodos normales para que los eventos extremos sean detectables
- No se usa LSTM para predicción de precios: no está justificado y el mercado argentino tiene demasiados shocks exógenos

---

## Estado del proyecto

- [x] Definir fuentes de datos (Rava, Docta, BCRA) y validar APIs con script de exploración
- [x] Diseñar schema de base de datos y generar migración inicial con Alembic
- [x] Crear schemas Pydantic y modelos SQLAlchemy
- [x] Correr migración y construir ETL de carga diaria (`src/etl.py`)
- [x] Notebook 01: EDA
- [x] Notebook 02: Curvas de tasas reales
- [x] Notebook 03: Nelson-Siegel (lecer / cer)
- [ ] Notebook 04: Clustering (validación lecer/cer + sub-estructura)
- [ ] Notebook 05: PCA sobre parámetros NS + feature engineering
- [ ] Notebook 06: Autoencoder PyTorch
- [ ] Notebook 07: Síntesis de señales
