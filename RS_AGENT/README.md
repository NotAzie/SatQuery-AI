# SatQuery AI

SatQuery AI is a query-routing engine for remote-sensing workflows. Its core loop is:

1. Understand the user question.
2. Select the required SatQuery capability.
3. Load matching guidance when configured.
4. Call the capability adapter.
5. Return the adapter result.

The routing brain is implemented and runnable. Image capabilities are being
integrated incrementally; captioning is the first real adapter, while the other
capabilities remain placeholders until their inference backends are attached.
An optional external remote-sensing VLM adapter is available for scene
classification, visual question answering, and grounding.

## Install

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -e .
```

Copy `.env.example` to `.env` and configure an OpenAI-compatible provider. The
included configuration uses Groq with `openai/gpt-oss-20b`.

## Run the demo

```bash
python examples/demo.py --question "Can you upscale this image?"
```

Use `--image path/to/image.png` to provide a different image path. Captioning uses
the lazy `Salesforce/blip-image-captioning-base` model from Hugging Face and
downloads its weights on first use. The other capability adapters still return
fixed placeholder responses. The captioning dependency set is `transformers`,
`torch`, and `pillow`; `pip install -r requirements.txt` installs them.

## Package structure

```text
satquery_ai/
  configuration.py          Configuration and paths
  task_catalog.py           Task vocabulary and label matching
  orchestration/            Query understanding and routing
  guidance/                 Task guidance service
  tools/                    Capability catalog and adapters
  knowledge.py              Optional knowledge-engine boundary
```

`rs_agent/` remains as a compatibility namespace for existing integrations. New
code should import from `satquery_ai`.

```python
from satquery_ai import SatQueryAI, load_config, resolve_path

config = load_config()
engine = SatQueryAI.from_config(config)
result = engine.run("Describe this scene", str(resolve_path("examples/sample.png")))
```

## Optional knowledge service

Attach an initialized compatible knowledge engine before issuing knowledge queries:

```python
from satquery_ai import configure_knowledge

configure_knowledge(knowledge_engine)
```

## Checks

```bash
pytest -q
python examples/demo.py --help
```

The bundled `dualrag/` directory remains available for its separate knowledge
experiments. It is not required for the standard SatQuery routing demo.

## Optional remote-sensing VLM

The GeoChat adapter does not copy or modify the upstream project. Install the
upstream runtime in a separate directory, retain its license and attribution, and
download its published checkpoint according to its model documentation. Then set:

```powershell
$env:GEOCHAT_SOURCE_PATH = "C:\path\to\external\GeoChat"
$env:GEOCHAT_MODEL_PATH = "C:\path\to\models\geochat-7B"
$env:GEOCHAT_DEVICE = "cuda"
```

The checkpoint is a large 7B model and is intended for a CUDA-capable machine.
The adapter loads it lazily on the first VQA, scene, or grounding request. Without
these variables, those tools return a setup message instead of a fake answer.

Run real routed requests after configuring the checkpoint:

```powershell
python examples/demo.py --question "What objects are visible in this image?"
python examples/demo.py --question "Classify the scene as airport, residential, industrial, or agricultural."
python examples/demo.py --question "Ground all buildings and report their locations."
```

Grounding responses preserve the model's textual region format. Rendering those
regions on an output image is intentionally not added yet.
