# Análisis: Chatbot Inteligente con Documentos Institucionales (Tortugas)

## Tabla de Contenidos

1. [Resumen Ejecutivo](#resumen-ejecutivo)
2. [Contexto del Proyecto](#contexto-del-proyecto)
3. [Análisis de Viabilidad](#análisis-de-viabilidad)
4. [Arquitectura Propuesta](#arquitectura-propuesta)
5. [Tecnologías y Modelos de IA](#tecnologías-y-modelos-de-ia)
6. [PgBouncer: Connection Pooling](#pgbouncer-connection-pooling)
7. [Estimaciones de Recursos](#estimaciones-de-recursos)
8. [Plan de Implementación](#plan-de-implementación)
9. [Pros y Contras](#pros-y-contras)
10. [Recomendaciones Finales](#recomendaciones-finales)
11. [Presupuesto y Alternativas](#presupuesto-y-alternativas)

---

## Resumen Ejecutivo

### Veredicto: ✅ VIABLE CON CONSIDERACIONES

El proyecto es **técnicamente viable** pero requiere ajustes significativos debido a la ausencia de GPU dedicada. La arquitectura propuesta utiliza **RAG (Retrieval-Augmented Generation)** con modelos open-source optimizados para CPU.

| Aspecto | Evaluación |
|---------|------------|
| **Viabilidad técnica** | ✅ Alta |
| **Recursos actuales** | ⚠️ Limitados (sin GPU) |
| **Complejidad** | ⚠️ Media-Alta |
| **Escalabilidad** | ✅ Buena con contenedor separado |
| **Tiempo estimado** | 4-8 semanas |

### Resumen de la Propuesta

```
┌─────────────────────────────────────────────────────────────────────────┐
│     USUARIOS (≤5k potenciales, ~100-500 consultas/hora pico)           │
└────────────────────────────┬────────────────────────────────────────────┘
                             │
                    ┌────────▼────────┐
                    │     NGINX       │
                    │  (Load Balancer)│
                    └────────┬────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
┌───────▼───────┐  ┌─────────▼────────┐  ┌───────▼───────┐
│    Backend    │  │   Chatbot API    │  │   PgBouncer   │
│ (Flask/FastAPI)│  │  (Contenedor)    │  │  (Opcional)   │
└───────┬───────┘  └─────────┬────────┘  └───────┬───────┘
        │                    │                    │
        │           ┌────────▼────────┐           │
        │           │   Vector DB     │           │
        │           │   (ChromaDB)    │           │
        │           └─────────────────┘           │
        │                                         │
        └──────────────────┬──────────────────────┘
                           │
                  ┌────────▼────────┐
                  │   PostgreSQL    │
                  └─────────────────┘
```

---

## Contexto del Proyecto

### Infraestructura Actual

| Componente | Especificación |
|------------|----------------|
| **RAM** | 31 GB |
| **CPU** | 12 cores |
| **GPU** | ❌ No dedicada |
| **Stack** | Flask + PostgreSQL + Redis + Docker Compose |
| **Producción** | Blue-Green deployment |

### Requisitos del Chatbot

- **Fuente de datos**: Documentos variados (PDF, Word, Excel) de todos los departamentos
- **Usuarios**: ~5,000 potenciales (estimado ~100-500 consultas concurrentes en pico)
- **Objetivo**: Responder dudas de alumnos sobre procesos institucionales
- **Integración**: Nueva aplicación dentro del proyecto ITCJ

---

## Análisis de Viabilidad

### Desafío Principal: Sin GPU

La ausencia de GPU dedicada es el factor más crítico. Los LLMs modernos (GPT-4, Llama 70B, etc.) están diseñados para GPU. Sin embargo, existen alternativas viables:

| Opción | Viabilidad | Latencia Esperada |
|--------|-----------|-------------------|
| **Modelos pequeños cuantizados (CPU)** | ✅ Alta | 5-30 segundos |
| **APIs externas (backup)** | ✅ Alta | 1-3 segundos |
| **Modelos grandes locales** | ❌ No viable | Minutos |

### ¿Por qué RAG y no Fine-tuning?

**RAG (Retrieval-Augmented Generation)** es la arquitectura correcta para este caso:

```
┌─────────────────────────────────────────────────────────────────────┐
│  Pregunta del usuario: "¿Cómo solicito mi constancia de estudios?" │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                    ┌────────▼─────────┐
                    │ 1. EMBEDDING     │  Convierte pregunta a vector
                    │    (all-MiniLM)  │  (~50ms)
                    └────────┬─────────┘
                             │
                    ┌────────▼─────────┐
                    │ 2. BÚSQUEDA      │  Encuentra documentos relevantes
                    │    en Vector DB  │  (ChromaDB) (~100ms)
                    └────────┬─────────┘
                             │
                    ┌────────▼─────────┐
                    │ 3. CONTEXTO      │  Extrae fragmentos relevantes
                    │    + PREGUNTA    │  de las "tortugas"
                    └────────┬─────────┘
                             │
                    ┌────────▼─────────┐
                    │ 4. LLM           │  Genera respuesta usando
                    │    (Llama/Mistral)│  el contexto (~5-20s en CPU)
                    └────────┬─────────┘
                             │
                    ┌────────▼─────────┐
                    │ 5. RESPUESTA     │  "Para solicitar tu constancia..."
                    └──────────────────┘
```

**Ventajas de RAG:**
- ✅ No requiere reentrenar el modelo cuando agreguen nuevos documentos
- ✅ La información siempre está actualizada
- ✅ El LLM "cita" fuentes específicas
- ✅ Menor costo computacional que fine-tuning

---

## Arquitectura Propuesta

### Nueva Estructura de Contenedores

```yaml
# docker-compose.chatbot.yml (extensión del actual)
services:
  chatbot:
    build:
      context: .
      dockerfile: docker/chatbot/Dockerfile
    volumes:
      - ./itcj/apps/chatbot:/app/chatbot:ro
      - ./instance/chatbot/documents:/app/documents:ro
      - ./instance/chatbot/vectordb:/app/vectordb
    environment:
      - LLM_MODEL=mistral-7b-instruct-v0.2.Q4_K_M.gguf
      - EMBEDDING_MODEL=all-MiniLM-L6-v2
      - VECTOR_DB_PATH=/app/vectordb
      - MAX_CONCURRENT_REQUESTS=4
    deploy:
      resources:
        limits:
          cpus: '8'
          memory: 16G
        reservations:
          cpus: '4'
          memory: 8G
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8001/health"]
      interval: 30s
      timeout: 10s
      retries: 3
    ports:
      - "127.0.0.1:8001:8001"

  chromadb:
    image: chromadb/chroma:latest
    volumes:
      - chroma_data:/chroma/chroma
    ports:
      - "127.0.0.1:8002:8000"
    environment:
      - ANONYMIZED_TELEMETRY=False

  pgbouncer:
    image: pgbouncer/pgbouncer:latest
    environment:
      - DATABASES_HOST=postgres
      - DATABASES_PORT=5432
      - DATABASES_USER=${DB_USER}
      - DATABASES_PASSWORD=${DB_PASSWORD}
      - DATABASES_DBNAME=${DB_NAME}
      - PGBOUNCER_POOL_MODE=transaction
      - PGBOUNCER_MAX_CLIENT_CONN=500
      - PGBOUNCER_DEFAULT_POOL_SIZE=20
    depends_on:
      - postgres
    ports:
      - "127.0.0.1:6432:6432"

volumes:
  chroma_data:
```

### Nueva Aplicación: `itcj/apps/chatbot/`

```
itcj/apps/chatbot/
├── __init__.py
├── routes/
│   ├── __init__.py
│   └── chat.py              # Endpoints de chat (SSE o WebSocket)
├── services/
│   ├── __init__.py
│   ├── document_processor.py # Procesa PDFs, Word, Excel
│   ├── embedding_service.py  # Genera embeddings
│   ├── vector_store.py       # Interfaz con ChromaDB
│   └── llm_service.py        # Interfaz con el modelo
├── models/
│   ├── __init__.py
│   ├── chat_session.py       # Historial de conversaciones
│   └── document.py           # Metadatos de documentos indexados
├── templates/
│   └── chat/
│       ├── index.html        # Interfaz del chatbot
│       └── widget.html       # Widget embebible
└── static/
    ├── css/
    │   └── chat.css
    └── js/
        └── chat.js
```

### Servicio del Chatbot (Contenedor Separado)

**Archivo: `docker/chatbot/chatbot_api.py`**

```python
"""
Servicio independiente del chatbot usando FastAPI + llama-cpp-python.
Corre en su propio contenedor para aislar la carga de IA.
"""
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from llama_cpp import Llama
from sentence_transformers import SentenceTransformer
import chromadb
import os
import asyncio
from concurrent.futures import ThreadPoolExecutor

app = FastAPI(title="ITCJ Chatbot API")

# Configuración
MODEL_PATH = os.getenv("LLM_MODEL_PATH", "/app/models/mistral-7b.gguf")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
CHROMA_HOST = os.getenv("CHROMA_HOST", "chromadb")

# Modelos (cargados una sola vez al inicio)
llm = None
embedder = None
chroma_client = None
collection = None
executor = ThreadPoolExecutor(max_workers=4)

@app.on_event("startup")
async def load_models():
    global llm, embedder, chroma_client, collection
    
    # Cargar LLM (cuantizado para CPU)
    llm = Llama(
        model_path=MODEL_PATH,
        n_ctx=4096,        # Contexto (tokens)
        n_threads=8,       # Hilos CPU
        n_batch=512,       # Batch size
        verbose=False
    )
    
    # Cargar modelo de embeddings (muy ligero)
    embedder = SentenceTransformer(EMBEDDING_MODEL)
    
    # Conectar a ChromaDB
    chroma_client = chromadb.HttpClient(host=CHROMA_HOST, port=8000)
    collection = chroma_client.get_or_create_collection(
        name="tortugas",
        metadata={"hnsw:space": "cosine"}
    )

class ChatRequest(BaseModel):
    question: str
    session_id: str | None = None
    max_tokens: int = 512
    temperature: float = 0.7

class ChatResponse(BaseModel):
    answer: str
    sources: list[dict]
    session_id: str

@app.post("/api/chat")
async def chat(request: ChatRequest):
    """Endpoint principal de chat con RAG."""
    
    # 1. Generar embedding de la pregunta
    query_embedding = embedder.encode(request.question).tolist()
    
    # 2. Buscar documentos relevantes en ChromaDB
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=5,
        include=["documents", "metadatas", "distances"]
    )
    
    # 3. Construir contexto
    context_parts = []
    sources = []
    for i, doc in enumerate(results["documents"][0]):
        context_parts.append(f"[Documento {i+1}]: {doc}")
        sources.append({
            "title": results["metadatas"][0][i].get("title", "Sin título"),
            "department": results["metadatas"][0][i].get("department", "Desconocido"),
            "relevance": 1 - results["distances"][0][i]
        })
    
    context = "\n\n".join(context_parts)
    
    # 4. Construir prompt
    prompt = f"""<|im_start|>system
Eres el asistente virtual del Instituto Tecnológico de Ciudad Juárez (ITCJ).
Tu rol es ayudar a estudiantes con información sobre procesos académicos y administrativos.
Responde SOLO con información del contexto proporcionado.
Si no encuentras la información, indica que el estudiante debe acudir al departamento correspondiente.
Sé conciso y amable.
<|im_end|>
<|im_start|>user
CONTEXTO DE DOCUMENTOS INSTITUCIONALES:
{context}

PREGUNTA DEL ESTUDIANTE:
{request.question}
<|im_end|>
<|im_start|>assistant
"""

    # 5. Generar respuesta (en thread pool para no bloquear)
    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(
        executor,
        lambda: llm(
            prompt,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
            stop=["<|im_end|>", "<|im_start|>"]
        )
    )
    
    answer = response["choices"][0]["text"].strip()
    
    return ChatResponse(
        answer=answer,
        sources=sources,
        session_id=request.session_id or "new_session"
    )

@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest):
    """Versión con streaming para mejor UX."""
    
    # Similar al anterior pero con streaming
    query_embedding = embedder.encode(request.question).tolist()
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=5,
        include=["documents", "metadatas"]
    )
    
    context = "\n\n".join([f"[Doc {i+1}]: {doc}" 
                          for i, doc in enumerate(results["documents"][0])])
    
    prompt = f"""<|im_start|>system
Eres el asistente virtual del ITCJ. Responde solo con el contexto dado.
<|im_end|>
<|im_start|>user
CONTEXTO:
{context}

PREGUNTA:
{request.question}
<|im_end|>
<|im_start|>assistant
"""

    async def generate():
        for output in llm(
            prompt,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
            stop=["<|im_end|>"],
            stream=True
        ):
            token = output["choices"][0]["text"]
            yield f"data: {token}\n\n"
        yield "data: [DONE]\n\n"
    
    return StreamingResponse(generate(), media_type="text/event-stream")

@app.get("/health")
async def health():
    return {"status": "healthy", "model_loaded": llm is not None}
```

---

## Tecnologías y Modelos de IA

### Modelos Recomendados para CPU (Sin GPU)

| Modelo | RAM Requerida | Latencia Estimada | Calidad | Recomendación |
|--------|--------------|-------------------|---------|---------------|
| **Mistral-7B-Instruct Q4_K_M** | 6-8 GB | 10-20s | ⭐⭐⭐⭐ | ✅ **Recomendado** |
| **Llama-3-8B-Instruct Q4_K_M** | 6-8 GB | 10-25s | ⭐⭐⭐⭐ | ✅ Alternativa |
| **Phi-3-mini Q4_K_M** | 3-4 GB | 5-15s | ⭐⭐⭐ | Opción ligera |
| **TinyLlama-1.1B** | 1-2 GB | 2-5s | ⭐⭐ | Solo para pruebas |

> **Nota:** Los modelos "Q4_K_M" están cuantizados a 4 bits, sacrificando ~5% de calidad por ~75% menos uso de memoria.

### Stack de IA Propuesto

```
┌─────────────────────────────────────────────────────────────────────┐
│                         STACK DE IA                                 │
├─────────────────────────────────────────────────────────────────────┤
│  Embeddings:     all-MiniLM-L6-v2 (Sentence Transformers)          │
│                  - Modelo de 80MB, muy rápido en CPU                │
│                  - 384 dimensiones                                  │
├─────────────────────────────────────────────────────────────────────┤
│  Vector DB:      ChromaDB                                           │
│                  - Open source, ligero                              │
│                  - Perfecta integración con Python                  │
│                  - Alternativa: Qdrant (más features)               │
├─────────────────────────────────────────────────────────────────────┤
│  LLM:            Mistral-7B-Instruct (via llama-cpp-python)        │
│                  - Backend optimizado para CPU (llama.cpp)          │
│                  - Cuantización Q4_K_M para rendimiento             │
├─────────────────────────────────────────────────────────────────────┤
│  Procesadores:   - PyMuPDF (PDFs)                                  │
│                  - python-docx (Word)                               │
│                  - openpyxl/pandas (Excel)                          │
│                  - Unstructured (parser universal)                  │
└─────────────────────────────────────────────────────────────────────┘
```

### Librerías Requeridas

```txt
# requirements-chatbot.txt
fastapi==0.115.0
uvicorn[standard]==0.32.0
llama-cpp-python==0.2.88
sentence-transformers==3.0.1
chromadb==0.5.5
langchain==0.2.16
langchain-community==0.2.16
pymupdf==1.24.10          # Para PDFs
python-docx==1.1.2        # Ya lo tienen
openpyxl==3.1.5           # Para Excel
unstructured==0.15.12     # Parser universal
tiktoken==0.7.0           # Tokenización
```

---

## PgBouncer: Connection Pooling

### ¿Es Necesario PgBouncer?

**Para 5k usuarios potenciales y ~100-500 consultas concurrentes: NO es estrictamente necesario, pero es RECOMENDABLE.**

| Escenario | Sin PgBouncer | Con PgBouncer |
|-----------|---------------|---------------|
| Conexiones PostgreSQL | 20-100 activas | Pool de 20, máx 500 clientes |
| Overhead de conexión | Alto (~50-100ms por nueva) | Mínimo (reutiliza) |
| RAM PostgreSQL | ~10MB por conexión | Mínimo |
| Complejidad | Simple | Moderada |

### Configuración Propuesta

```ini
# pgbouncer.ini
[databases]
itcj = host=postgres port=5432 dbname=itcj

[pgbouncer]
listen_addr = 0.0.0.0
listen_port = 6432
auth_type = md5
auth_file = /etc/pgbouncer/userlist.txt

# Pool settings
pool_mode = transaction       # Libera conexión al terminar transacción
default_pool_size = 20        # Conexiones REALES a PostgreSQL
min_pool_size = 5
reserve_pool_size = 5
max_client_conn = 500         # Máximo de clientes (apps)
max_db_connections = 50       # Máximo por base de datos

# Timeouts
server_idle_timeout = 600
server_lifetime = 3600
client_idle_timeout = 0

# Stats
stats_users = pgbouncer
admin_users = pgbouncer
```

### Cuándo Activar PgBouncer

| Indicador | Umbral para Activar |
|-----------|---------------------|
| Conexiones activas PostgreSQL | > 50 sostenidas |
| Tiempo de conexión | > 50ms promedio |
| Errores "too many connections" | Cualquiera |
| Uso de RAM PostgreSQL | > 2GB por conexiones |

### Migración del Backend a PgBouncer

```python
# config.py - cambiar URL si usan PgBouncer
import os

class Config:
    # Sin PgBouncer (actual)
    # SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL")
    
    # Con PgBouncer
    PGBOUNCER_ENABLED = os.getenv("PGBOUNCER_ENABLED", "false").lower() == "true"
    
    if PGBOUNCER_ENABLED:
        # PgBouncer usa puerto 6432
        SQLALCHEMY_DATABASE_URI = os.getenv(
            "DATABASE_URL", 
            "postgresql://user:pass@pgbouncer:6432/itcj"
        )
        # Importante: preparadas statements no funcionan bien con transaction mode
        SQLALCHEMY_ENGINE_OPTIONS = {
            "pool_pre_ping": True,
            "pool_size": 5,        # Pequeño pool local
            "max_overflow": 0,     # PgBouncer maneja el overflow
            "connect_args": {
                "options": "-c statement_timeout=30000"
            }
        }
    else:
        SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL")
```

---

## Estimaciones de Recursos

### Distribución de Recursos Propuesta

```
                    SERVIDOR ACTUAL (31GB RAM, 12 CPU)
┌─────────────────────────────────────────────────────────────────────┐
│                                                                     │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐     │
│  │   PostgreSQL    │  │     Redis       │  │   PgBouncer     │     │
│  │   4GB RAM       │  │   512MB RAM     │  │   256MB RAM     │     │
│  │   2 CPU         │  │   0.5 CPU       │  │   0.5 CPU       │     │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘     │
│                                                                     │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐     │
│  │   Backend       │  │   Nginx         │  │   ChromaDB      │     │
│  │   (Flask)       │  │                 │  │                 │     │
│  │   4GB RAM       │  │   256MB RAM     │  │   2GB RAM       │     │
│  │   2 CPU         │  │   0.5 CPU       │  │   1 CPU         │     │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘     │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                    CHATBOT SERVICE                          │   │
│  │                                                             │   │
│  │   LLM (Mistral-7B Q4):  8GB RAM                            │   │
│  │   Embeddings:           1GB RAM                            │   │
│  │   FastAPI:              512MB RAM                          │   │
│  │   Buffer:               2GB RAM                            │   │
│  │                                                             │   │
│  │   Total: 11.5GB RAM, 6 CPU                                 │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  RESERVA SO: 4GB RAM                                               │
│                                                                     │
│  TOTAL ASIGNADO: ~27GB de 31GB ✅                                  │
└─────────────────────────────────────────────────────────────────────┘
```

### Capacidad Estimada

| Métrica | Estimación |
|---------|------------|
| Consultas concurrentes al chatbot | 2-4 (por limitación CPU) |
| Throughput | 6-12 consultas/minuto |
| Latencia promedio | 10-25 segundos |
| Usuarios concurrentes (chat abierto) | 50-200 |
| Cola de espera máxima | 20 consultas |

### ⚠️ Limitación Crítica

**Con CPU solamente, el throughput está limitado a ~6-12 consultas/minuto.** En hora pico (ej: inicio de semestre), podría haber colas de espera.

**Mitigaciones:**
1. Caché de respuestas frecuentes (Redis)
2. Respuestas "enlatadas" para preguntas comunes
3. Sistema de cola con prioridad
4. Limitar sesiones concurrentes por usuario

---

## Plan de Implementación

### Fase 1: Fundamentos (Semana 1-2)

```
┌─────────────────────────────────────────────────────────────────────┐
│  1.1 Crear estructura de la aplicación chatbot                     │
│      - itcj/apps/chatbot/                                          │
│      - Modelos de base de datos                                    │
│      - Blueprints básicos                                          │
│                                                                     │
│  1.2 Configurar ChromaDB                                           │
│      - Añadir contenedor al docker-compose                         │
│      - Probar conexión                                             │
│                                                                     │
│  1.3 Procesador de documentos                                      │
│      - Servicio para extraer texto de PDF/Word/Excel               │
│      - Chunking (dividir en fragmentos de 500-1000 tokens)         │
│      - Tests con documentos de ejemplo                             │
└─────────────────────────────────────────────────────────────────────┘
```

### Fase 2: Indexación (Semana 2-3)

```
┌─────────────────────────────────────────────────────────────────────┐
│  2.1 Servicio de embeddings                                        │
│      - Integración Sentence Transformers                           │
│      - Batch processing para documentos largos                     │
│                                                                     │
│  2.2 Pipeline de indexación                                        │
│      - Upload de documentos (integrar con app de tortugas)         │
│      - Indexación automática en ChromaDB                           │
│      - Metadatos (departamento, fecha, tipo)                       │
│                                                                     │
│  2.3 Herramientas de administración                                │
│      - Re-indexar documentos                                       │
│      - Ver estadísticas de vectores                                │
│      - Eliminar documentos obsoletos                               │
└─────────────────────────────────────────────────────────────────────┘
```

### Fase 3: Servicio LLM (Semana 3-4)

```
┌─────────────────────────────────────────────────────────────────────┐
│  3.1 Contenedor del chatbot                                        │
│      - Dockerfile con llama-cpp-python                             │
│      - Descargar modelo Mistral-7B                                 │
│      - API FastAPI independiente                                   │
│                                                                     │
│  3.2 Endpoint de chat                                              │
│      - RAG completo (búsqueda + generación)                        │
│      - Streaming de respuestas                                     │
│      - Manejo de errores                                           │
│                                                                     │
│  3.3 Optimizaciones                                                │
│      - Caché de embeddings de consultas frecuentes                 │
│      - Pool de workers                                             │
│      - Timeout y reintentos                                        │
└─────────────────────────────────────────────────────────────────────┘
```

### Fase 4: Integración Frontend (Semana 4-5)

```
┌─────────────────────────────────────────────────────────────────────┐
│  4.1 Interfaz de chat                                              │
│      - Componente de chat estilo burbuja                           │
│      - Indicador de "escribiendo..."                               │
│      - Mostrar fuentes/documentos consultados                      │
│                                                                     │
│  4.2 Widget embebible                                              │
│      - Botón flotante para otras apps                              │
│      - Modal de chat                                               │
│                                                                     │
│  4.3 Historial                                                     │
│      - Guardar conversaciones                                      │
│      - Continuar sesiones anteriores                               │
└─────────────────────────────────────────────────────────────────────┘
```

### Fase 5: PgBouncer + Producción (Semana 5-6)

```
┌─────────────────────────────────────────────────────────────────────┐
│  5.1 PgBouncer (si es necesario)                                   │
│      - Añadir contenedor                                           │
│      - Configurar y probar                                         │
│      - Migrar conexiones del backend                               │
│                                                                     │
│  5.2 Monitoreo                                                     │
│      - Métricas de uso del chatbot                                 │
│      - Alertas de saturación                                       │
│      - Dashboard básico                                            │
│                                                                     │
│  5.3 Despliegue                                                    │
│      - Integrar en deploy.sh                                       │
│      - Health checks                                               │
│      - Rollback plan                                               │
└─────────────────────────────────────────────────────────────────────┘
```

### Fase 6: Mejora Continua (Semana 6-8+)

```
┌─────────────────────────────────────────────────────────────────────┐
│  6.1 Feedback loop                                                 │
│      - Botones de "útil/no útil"                                   │
│      - Recolección de preguntas sin respuesta                      │
│                                                                     │
│  6.2 Fine-tuning del sistema                                       │
│      - Ajustar prompts basado en feedback                          │
│      - Optimizar chunking de documentos                            │
│      - Mejorar búsqueda semántica                                  │
│                                                                     │
│  6.3 Expansión (opcional)                                          │
│      - Soporte multiidioma                                         │
│      - Integración con calendario académico                        │
│      - Notificaciones proactivas                                   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Pros y Contras

### ✅ Pros

| Aspecto | Beneficio |
|---------|-----------|
| **Valor para estudiantes** | Respuestas 24/7 sobre procesos institucionales |
| **Reducción de carga** | Menos consultas repetitivas a departamentos |
| **Centralización** | Toda la info institucional en un solo lugar |
| **Escalabilidad técnica** | Contenedor separado permite escalar independientemente |
| **Open Source** | Sin costos de licencia de IA |
| **Privacidad** | Datos no salen del servidor |
| **Integración natural** | Reutiliza sistema de tortugas existente |
| **Experiencia de usuario** | Interfaz moderna de chat |

### ❌ Contras

| Aspecto | Desafío | Mitigación |
|---------|---------|------------|
| **Latencia** | 10-25s por respuesta (CPU) | Streaming + cache |
| **Capacidad limitada** | 6-12 consultas/minuto | Cola de espera + respuestas frecuentes cacheadas |
| **Complejidad operacional** | Nuevos contenedores + modelos | Documentación detallada |
| **Uso de recursos** | ~12GB RAM + 6 CPU | Reservar recursos exclusivos |
| **Calidad de respuestas** | Modelos pequeños menos precisos | Prompts bien diseñados + fallback |
| **Mantenimiento** | Actualizar modelos, reindexar | Automatizar con scripts |
| **Alucinaciones** | LLM puede inventar info | RAG limita esto + disclaimer |
| **Curva de aprendizaje** | Equipo debe aprender IA | Capacitación gradual |

### ⚠️ Riesgos

| Riesgo | Probabilidad | Impacto | Mitigación |
|--------|-------------|---------|------------|
| Respuestas incorrectas | Media | Alto | Disclaimer + feedback + revisión humana |
| Sobrecarga del servidor | Media | Medio | Limitar concurrencia + monitoreo |
| Documentos desactualizados | Alta | Medio | Pipeline de actualización automático |
| Expectativas no cumplidas | Media | Alto | MVP primero, iterar con feedback |

---

## Recomendaciones Finales

### Decisión: ¿Implementar o No?

**RECOMENDACIÓN: ✅ SÍ, implementar con enfoque incremental**

El proyecto es valioso y técnicamente viable. Las limitaciones de hardware se pueden mitigar con:

1. **Expectativas realistas**: Latencia de 10-25s es aceptable para consultas complejas
2. **Caché agresivo**: Preguntas frecuentes respondidas en <1s
3. **Feedback temprano**: MVP en 4 semanas, iterar después
4. **Opción de GPU futura**: Si el chatbot es exitoso, justifica inversión en GPU

### Orden de Prioridades

```
┌─────────────────────────────────────────────────────────────────────┐
│  PRIORIDAD 1 (Hacer primero)                                       │
│  ───────────────────────────                                       │
│  • MVP del chatbot con documentos de prueba                        │
│  • Interfaz básica de chat                                         │
│  • Métricas de uso                                                 │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│  PRIORIDAD 2 (Después del MVP)                                     │
│  ─────────────────────────────                                     │
│  • Integración con app de tortugas                                 │
│  • Pipeline de indexación automática                               │
│  • Caché de respuestas                                             │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│  PRIORIDAD 3 (Si hay demanda)                                      │
│  ─────────────────────────────                                     │
│  • PgBouncer (solo si hay problemas de conexiones)                 │
│  • Widget embebible en otras apps                                  │
│  • Historial de conversaciones                                     │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│  FUTURO (Si el chatbot es exitoso)                                 │
│  ─────────────────────────────────                                 │
│  • GPU dedicada para mejor rendimiento                             │
│  • Modelos más grandes (Llama 70B)                                 │
│  • API de OpenAI como fallback                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### PgBouncer: ¿Sí o No?

**RECOMENDACIÓN: Preparar pero NO activar inicialmente**

- Crear la configuración de PgBouncer
- Tenerlo listo en docker-compose con `profiles: [pgbouncer]`
- Activar solo si:
  - Conexiones activas > 50 sostenidas
  - Errores de "too many connections"
  - Latencia de conexión > 50ms

---

## Presupuesto y Alternativas

### Opción A: Todo Local (Recomendada)

| Componente | Costo |
|------------|-------|
| Modelos Open Source | $0 |
| ChromaDB | $0 |
| Hardware adicional | $0 (usa servidor actual) |
| **Total** | **$0** |

**Limitación**: 6-12 consultas/minuto, latencia 10-25s

### Opción B: Híbrido (Fallback a API)

| Componente | Costo Mensual |
|------------|---------------|
| Local (mayoría de consultas) | $0 |
| OpenAI API (fallback/pico) | ~$20-100 |
| **Total** | **$20-100/mes** |

**Beneficio**: Mejor UX en hora pico

### Opción C: GPU Dedicada (Futuro)

| Componente | Costo |
|------------|-------|
| GPU RTX 4060/4070 (usado) | ~$300-500 |
| GPU de servidor (A4000) | ~$1,000-2,000 |

**Beneficio**: 3-5x más rápido, modelos más grandes

### Opción D: API Completa (No recomendada)

| Componente | Costo Mensual |
|------------|---------------|
| OpenAI API (5k usuarios) | $200-500 |
| Azure OpenAI | similar |
| **Total** | **$200-500/mes** |

**Desventaja**: Datos salen del servidor, costo recurrente

---

## Checklist de Inicio

Antes de comenzar la implementación:

- [ ] Confirmar espacio en disco para modelo (~5GB)
- [ ] Obtener documentos de prueba (5-10 tortugas de ejemplo)
- [ ] Definir alcance del MVP (¿qué departamentos primero?)
- [ ] Asignar tiempo de desarrollador (4+ semanas)
- [ ] Comunicar expectativas de latencia a stakeholders
- [ ] Preparar disclaimer legal para respuestas de IA

---

## Conclusión

El chatbot institucional es un proyecto **viable y valioso** que aprovecha la infraestructura existente y la futura aplicación de tortugas. Las limitaciones de hardware (sin GPU) se pueden manejar con:

1. Modelos cuantizados optimizados para CPU
2. Arquitectura RAG que no requiere fine-tuning
3. Caché inteligente de respuestas frecuentes
4. Expectativas realistas de rendimiento

**La recomendación es proceder con el desarrollo**, comenzando con un MVP que valide la utilidad real del sistema antes de invertir en optimizaciones adicionales.

---

*Documento generado: 20 de febrero de 2026*  
*Versión: 1.0*
