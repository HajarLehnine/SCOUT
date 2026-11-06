# SCOUT

Global business intelligence workspace for evidence-backed market and business-idea research.

## Architecture

```text
User question
    -> Streamlit form (Python)
    -> web search across up to five countries or regions
    -> SQLite stores the research run and source snippets
    -> Local keyword retrieval ranks relevant evidence (the RAG retrieval step)
    -> Optional OpenAI-compatible model writes cited comparisons and a business plan
    -> Brief, source links, and Markdown/CSV/PDF exports
```

Python runs the workflow and web UI. SQLite keeps the history and collected evidence on your machine. Retrieval selects relevant snippets from that evidence; when an AI provider is configured, those snippets are passed as context so the model can synthesize rather than answer from memory alone. Without a key, SCOUT still produces a transparent, source-linked brief using the retrieved snippets.

## Run SCOUT

The project `.venv` uses Python 3.15, but ChromaDB's `onnxruntime` dependency is not available for that interpreter here. Use the compatible Python 3.13 environment at `%LOCALAPPDATA%\MIRA\rag-venv` for PDF RAG.

If that environment does not exist yet, create it and install the project requirements:

```powershell
& "C:\Users\Hp\anaconda3\python.exe" -m venv "$env:LOCALAPPDATA\MIRA\rag-venv"
& "$env:LOCALAPPDATA\MIRA\rag-venv\Scripts\python.exe" -m pip install -r requirements.txt
```

Start SCOUT with that environment:

   ```powershell
   & "$env:LOCALAPPDATA\MIRA\rag-venv\Scripts\python.exe" -m streamlit run app.py
   ```

Enter a business idea or market, one or more comma-separated countries/regions (up to five), and optional competitors, then run a scan. SCOUT searches for market, competitor, customer/pricing, and risk evidence and saves the results in `mira_data.sqlite3`. The AI analysis compares the selected regions, produces a cited SWOT and risk assessment, and gives an evidence-justified opportunity score out of 100. You can also generate a business plan and download it as a PDF.

### Interface language

Use the **Language** selector (English is the default) to localize the interface and choose the language for new AI analyses, PDF Q&A responses, and business plans. SCOUT supports English, French, Arabic, Spanish, Portuguese, German, Italian, Chinese, Japanese, Korean, Russian, Hindi, Turkish, and Dutch. Arabic uses right-to-left interface layout. Company names, URLs, source titles, citations, and retrieved source evidence remain unchanged. If a saved AI report was created in another language, SCOUT identifies its language and asks you to generate it again rather than showing it as if it matched the current selection.

The business-plan PDF uses installed Windows Unicode fonts when available. Arabic PDF text is shaped right-to-left; the Arabic shaping dependencies are included in `requirements.txt`.

### Structured business analysis

Select **Generate structured business analysis** on a saved scan. SCOUT searches for competitors even when none are entered, then asks the configured model to identify only competitors supported by retrieved sources. The report includes a SWOT for each identified competitor, sourced customer needs, business risks with impacts and mitigations, and observed competitor prices when the source provides them.

The opportunity score is calculated in the app by summing four evidence-based rubric components: market demand (0-30), competitive position (0-25), profitability (0-25), and ease of entry (0-20). Each component includes a justification and citations; unsupported points are rejected unless zero. Suggested pricing is labeled as an estimate and requires cited price evidence. When pricing evidence is missing, SCOUT says so and does not invent a numeric range. Search result snippets are not independently verified; follow the source links before relying on claims.

## Optional AI synthesis

Set the provider key in the environment before starting Streamlit. SCOUT does not accept API keys in the UI or save them in SQLite. In PowerShell, for example:

```powershell
$env:MIRA_AI_API_KEY = "<your-provider-key>"
```

The default endpoint is OpenAI-compatible; set these environment variables before starting Streamlit to use another compatible provider:

- `MIRA_AI_API_KEY` (required for AI analysis and business plans)
- `MIRA_AI_BASE_URL` (defaults to `https://api.openai.com/v1`)
- `MIRA_AI_MODEL` (defaults to `gpt-4o-mini`)

Retrieved snippets are sent to that provider only when you request AI analysis or a business plan. Source links remain visible so you can verify claims. AI scores are rubric-based assessments of the retrieved evidence, not forecasts or guarantees. Search snippets may be incomplete and are not independently verified; confirm important claims with primary sources.

## Build stages

1. **Global research:** collect market, competitor, customer/pricing, and risk evidence across up to five selected countries or regions.
2. **Evidence and memory:** rank snippets locally, save each run and its sources in SQLite, and reopen past work.
3. **AI decision support:** optionally create cited competitor SWOTs, customer/pricing and risk analysis, and a rubric-calculated opportunity score.
4. **Business planning:** generate and download a cited business-plan PDF from the selected idea and retrieved evidence.

These workflows are implemented in `app.py`. Search snippets are useful for discovery, not a substitute for reading and validating primary sources; market-size figures and forecasts should be checked at their source.
