import csv
import io
import os
import re
import sqlite3
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

import requests
import streamlit as st
from ddgs import DDGS
from ddgs.exceptions import DDGSException


APP_DIR = Path(__file__).resolve().parent
DATABASE_PATH = APP_DIR / "mira_data.sqlite3"
STOP_WORDS = {
	"about", "after", "also", "among", "and", "are", "as", "at", "be",
	"been", "before", "being", "between", "but", "by", "can", "could",
	"do", "for", "from", "have", "if", "in", "into", "is", "it", "its",
	"more", "most", "no", "not", "of", "on", "or", "our", "out", "over",
	"said", "such", "than", "that", "the", "their", "them", "there", "these",
	"they", "this", "those", "through", "to", "under", "up", "us", "was",
	"were", "what", "when", "where", "which", "while", "will", "with",
	"would", "your", "market", "markets", "company", "companies", "business",
	"businesses", "report", "reports", "news", "latest", "analysis", "research",
	"2025", "2026",
}


@contextmanager
def open_database():
	connection = sqlite3.connect(DATABASE_PATH)
	connection.row_factory = sqlite3.Row
	try:
		with connection:
			yield connection
	finally:
		connection.close()


def initialize_database():
	with open_database() as connection:
		connection.executescript(
			"""
			CREATE TABLE IF NOT EXISTS research_runs (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				market TEXT NOT NULL,
				region TEXT NOT NULL,
				competitors TEXT NOT NULL,
				created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
				ai_summary TEXT NOT NULL DEFAULT ''
			);
			CREATE TABLE IF NOT EXISTS sources (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				run_id INTEGER NOT NULL REFERENCES research_runs(id),
				category TEXT NOT NULL,
				competitor TEXT NOT NULL DEFAULT '',
				title TEXT NOT NULL,
				url TEXT NOT NULL,
				snippet TEXT NOT NULL
			);
			CREATE INDEX IF NOT EXISTS sources_run_id_idx ON sources(run_id);
			"""
		)


def save_research(market, region, competitors, sources):
	with open_database() as connection:
		cursor = connection.execute(
			"INSERT INTO research_runs (market, region, competitors) VALUES (?, ?, ?)",
			(market, region, ", ".join(competitors)),
		)
		run_id = cursor.lastrowid
		connection.executemany(
			"""
			INSERT INTO sources (run_id, category, competitor, title, url, snippet)
			VALUES (?, ?, ?, ?, ?, ?)
			""",
			[
				(
					run_id,
					source["category"],
					source["competitor"],
					source["title"],
					source["url"],
					source["snippet"],
				)
				for source in sources
			],
		)
	return run_id


def save_ai_summary(run_id, summary):
	with open_database() as connection:
		connection.execute(
			"UPDATE research_runs SET ai_summary = ? WHERE id = ?",
			(summary, run_id),
		)


def get_recent_runs(limit=20):
	with open_database() as connection:
		rows = connection.execute(
			"SELECT * FROM research_runs ORDER BY created_at DESC, id DESC LIMIT ?",
			(limit,),
		).fetchall()
	return [dict(row) for row in rows]


def get_research(run_id):
	with open_database() as connection:
		run = connection.execute(
			"SELECT * FROM research_runs WHERE id = ?", (run_id,)
		).fetchone()
		sources = connection.execute(
			"SELECT * FROM sources WHERE run_id = ? ORDER BY id", (run_id,)
		).fetchall()
	if run is None:
		return None
	return {"run": dict(run), "sources": [dict(source) for source in sources]}


def search_web(query, max_results):
	return DDGS().text(query, max_results=max_results)


def collect_sources(market, region, competitors):
	searches = [(f'"{market}" market trends {region}', "Market", "", 7)]
	searches.extend(
		(
			f'"{competitor}" {market} products pricing strategy {region}',
			"Competitor",
			competitor,
			3,
		)
		for competitor in competitors
	)

	sources = []
	seen = set()
	for query, category, competitor, count in searches:
		try:
			results = search_web(query, count)
		except DDGSException:
			continue
		for result in results:
			url = result.get("href", "").strip()
			title = result.get("title", "").strip()
			snippet = result.get("body", "").strip()
			key = (url, category, competitor.casefold())
			if not url or not title or key in seen:
				continue
			seen.add(key)
			sources.append(
				{
					"category": category,
					"competitor": competitor,
					"title": title,
					"url": url,
					"snippet": snippet,
				}
			)
	return sources


def search_terms(text):
	words = re.findall(r"[a-zA-Z][a-zA-Z0-9-]{1,}", text.casefold())
	return [word for word in words if word not in STOP_WORDS]


def rank_sources(query, sources, limit=8):
	query_counts = Counter(search_terms(query))
	scored = []
	for position, source in enumerate(sources):
		document_counts = Counter(
			search_terms(f'{source["title"]} {source["snippet"]}')
		)
		score = sum(
			min(count, 3) * min(document_counts[word], 4)
			for word, count in query_counts.items()
		)
		if score:
			scored.append((score, -position, source))
	return [item[2] for item in sorted(scored, reverse=True)[:limit]]


def recurring_terms(sources, query):
	excluded = set(search_terms(query))
	counts = Counter()
	for source in sources:
		counts.update(
			word
			for word in search_terms(f'{source["title"]} {source["snippet"]}')
			if word not in excluded
		)
	return [(word, count) for word, count in counts.most_common(6) if count > 1]


def clean_source_title(title):
	title = re.sub(r"(?<=\d)(?=[A-Z])", " ", title)
	words = re.sub(r"\s+", " ", title).strip().split()
	for length in range(min(8, len(words) // 2), 2, -1):
		seen = set()
		for position in range(len(words) - length + 1):
			phrase = tuple(word.casefold() for word in words[position : position + length])
			if phrase in seen:
				return " ".join(words[:position]).rstrip(" |:-")
			seen.add(phrase)
	return " ".join(words)


def make_local_brief(run, sources):
	query = f'{run["market"]} {run["region"]} {run["competitors"]}'
	source_refs = {source["id"]: f"S{index}" for index, source in enumerate(sources, 1)}
	ranked = rank_sources(query, sources, limit=5)
	lines = ["## Market snapshot"]
	if ranked:
		for source in ranked:
			ref = source_refs[source["id"]]
			snippet = source["snippet"] or "No search snippet was provided."
			title = clean_source_title(source["title"])
			lines.append(f'- **{title}** [{ref}]  ')
			lines.append(f'  {snippet[:420]}')
	else:
		lines.append("No evidence was returned for this search.")

	competitors = [name.strip() for name in run["competitors"].split(",") if name.strip()]
	if competitors:
		lines.extend(["", "## Competitor scan"])
		for competitor in competitors:
			matches = [
				source
				for source in sources
				if source["competitor"].casefold() == competitor.casefold()
			]
			if matches:
				refs = ", ".join(source_refs[source["id"]] for source in matches[:3])
				titles = "; ".join(
					clean_source_title(source["title"]) for source in matches[:2]
				)
				lines.append(f"- **{competitor}:** {titles} [{refs}]")
			else:
				lines.append(f"- **{competitor}:** No matching sources were found.")

	themes = recurring_terms(sources, query)
	lines.extend(["", "## Recurring terms in retrieved sources"])
	if themes:
		lines.append(", ".join(f"{word} ({count})" for word, count in themes))
		lines.append(
			"These are repeated words in search snippets, not validated growth trends."
		)
	else:
		lines.append("There is not enough repeated snippet text to surface themes.")
	lines.extend(
		[
			"",
			"---",
			"Directional scan only. Search snippets can be incomplete; verify figures "
			"and claims in the linked source before making decisions.",
		]
	)
	return "\n".join(lines)


def render_local_brief(run, sources):
	query = f'{run["market"]} {run["region"]} {run["competitors"]}'
	source_refs = {source["id"]: f"S{index}" for index, source in enumerate(sources, 1)}

	def section_title(title):
		st.markdown(
			f'<h2 class="brief-section-title">{title}</h2>',
			unsafe_allow_html=True,
		)

	section_title("Market snapshot")
	ranked = rank_sources(query, sources, limit=5)
	if ranked:
		for source in ranked:
			ref = source_refs[source["id"]]
			title = clean_source_title(source["title"]).replace("$", r"\$")
			snippet = (source["snippet"] or "No search snippet was provided.")[:420]
			st.markdown(f'**[{ref}] {title}**')
			st.markdown(snippet.replace("$", r"\$"))
	else:
		st.write("No evidence was returned for this search.")

	competitors = [name.strip() for name in run["competitors"].split(",") if name.strip()]
	if competitors:
		section_title("Competitor scan")
		columns = st.columns(min(len(competitors), 2))
		for index, competitor in enumerate(competitors):
			with columns[index % len(columns)]:
				with st.container(border=True, key=f"competitor-card-{index}"):
					st.markdown(f"**{competitor.replace('$', r'\$')}**")
					matches = [
						source
						for source in sources
						if source["competitor"].casefold() == competitor.casefold()
					]
					if matches:
						for source in matches[:3]:
							ref = source_refs[source["id"]]
							title = clean_source_title(source["title"]).replace("$", r"\$")
							snippet = (source["snippet"] or "No search snippet was provided.")[:280]
							st.markdown(f'**[{ref}] {title}**')
							st.markdown(snippet.replace("$", r"\$"))
					else:
						st.caption("No matching sources were found.")

	section_title("Recurring terms")
	themes = recurring_terms(sources, query)
	if themes:
		st.write(", ".join(f"{word} ({count})" for word, count in themes))
		st.caption("Repeated words in snippets are not validated growth trends.")
	else:
		st.write("There is not enough repeated snippet text to surface themes.")
	st.caption(
		"Directional scan only. Search snippets can be incomplete; verify figures "
		"and claims in the linked source before making decisions."
	)


def make_ai_brief(run, sources, api_key):
	query = f'{run["market"]} {run["region"]} {run["competitors"]}'
	ranked = rank_sources(query, sources, limit=12)
	source_refs = {
		source["id"]: f"S{index}" for index, source in enumerate(sources, 1)
	}
	source_text = "\n\n".join(
		f'[{source_refs[source["id"]]}] {source["title"]}\n'
		f'{source["snippet"]}\nURL: {source["url"]}'
		for source in ranked
	)
	model = os.getenv("MIRA_AI_MODEL", "gpt-4o-mini")
	base_url = os.getenv("MIRA_AI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
	response = requests.post(
		f"{base_url}/chat/completions",
		headers={"Authorization": f"Bearer {api_key}"},
		json={
			"model": model,
			"temperature": 0.2,
			"messages": [
				{
					"role": "system",
					"content": (
						"You are a careful market research analyst. Use only the "
						"provided search snippets. Do not invent market sizes, dates, "
						"or facts. Separate evidence from interpretation, state when "
						"evidence is thin, and cite every factual claim with its "
						"provided source ID such as [S2]. Return concise Markdown "
						"with a market overview, competitor observations, and signals "
						"to investigate next."
					),
				},
				{
					"role": "user",
					"content": (
						f'Market: {run["market"]}\nRegion: {run["region"]}\n'
						f'Competitors: {run["competitors"] or "None specified"}\n\n'
						f"Retrieved evidence:\n{source_text}"
					),
				},
			],
		},
		timeout=45,
	)
	response.raise_for_status()
	return response.json()["choices"][0]["message"]["content"].strip()


def make_markdown_export(run, brief, sources):
	lines = [
		f'# MIRA research brief: {run["market"]}',
		f'- Region: {run["region"]}',
		f'- Competitors: {run["competitors"] or "None specified"}',
		f'- Created: {run["created_at"]}',
		"",
		brief,
		"",
		"## Sources",
	]
	for index, source in enumerate(sources, 1):
		lines.append(f'{index}. [S{index}] [{source["title"]}]({source["url"]})')
	return "\n".join(lines)


def make_csv_export(sources):
	output = io.StringIO()
	writer = csv.writer(output)
	writer.writerow(["category", "competitor", "title", "url", "snippet"])
	for source in sources:
		writer.writerow(
			[
				source["category"],
				source["competitor"],
				source["title"],
				source["url"],
				source["snippet"],
			]
		)
	return output.getvalue()


def main():
	st.set_page_config(page_title="MIRA | Market Intelligence", page_icon="M", layout="wide")
	st.markdown(
		"""
		<style>
		:root { --mira-ink: #172522; --mira-green: #176b58; --mira-lime: #d3ef83; }
		.stApp { background: #f5f7f3; color: var(--mira-ink); }
		h1, h2, h3 { color: var(--mira-ink); font-family: Georgia, serif; }
		h1 { letter-spacing: 0; }
		[data-testid="stSidebar"] { background: #e8eee8; }
		div.stButton > button[kind="primary"] { background: var(--mira-green); border-color: var(--mira-green); }
		.stApp p, .stApp label, .stApp [data-testid="stMarkdownContainer"],
		[data-testid="stMetricLabel"] p, [data-testid="stMetricValue"] {
			color: var(--mira-ink);
		}
		.stApp input, .stApp textarea, .stApp [data-baseweb="select"] > div {
			background: #fff;
			color: var(--mira-ink);
			border-color: #cbd9d0;
		}
		div[data-testid="stMetric"] {
			background: #fff;
			border: 1px solid #e1e9e3;
			border-left: 4px solid var(--mira-green);
			border-radius: 12px;
			box-shadow: 0 8px 22px rgba(23, 37, 34, 0.08);
			padding: 16px 18px;
		}
		div[data-testid="stVerticalBlockBorderWrapper"] {
			background: #fff;
			border-color: #e1e9e3;
			border-radius: 12px;
			box-shadow: 0 8px 22px rgba(23, 37, 34, 0.07);
			padding: 8px;
		}
		div[data-testid="stVerticalBlockBorderWrapper"][class*="st-key-feature-card-"] {
			min-height: 180px;
		}
		.mira-hero {
			padding: 10px 0 24px;
			margin-bottom: 24px;
			border-bottom: 1px solid #dce6de;
			animation: mira-enter 500ms ease-out both;
		}
		.mira-wordmark {
			width: max-content;
			max-width: 100%;
			background: linear-gradient(105deg, #176b58 5%, #d3ef83 96%);
			background-clip: text;
			-webkit-background-clip: text;
			color: transparent !important;
			font-family: Georgia, serif;
			font-size: 4rem;
			font-weight: 800;
			line-height: 1;
		}
		.mira-tagline {
			margin-top: 10px;
			color: var(--mira-green);
			font-size: 1.25rem;
			font-weight: 700;
		}
		.mira-hero p { margin: 8px 0 0; color: #41534d; }
		.feature-kicker { color: var(--mira-green); font-size: 0.75rem; font-weight: 700; }
		.brief-section-title, div[data-testid="stMarkdownContainer"] h2 {
			color: var(--mira-green);
			font-family: Georgia, serif;
			font-size: 1.8rem;
			font-weight: 700;
			line-height: 1.2;
			margin: 1.8rem 0 0.8rem;
		}
		@keyframes mira-enter {
			from { opacity: 0; transform: translateY(8px); }
			to { opacity: 1; transform: translateY(0); }
		}
		@media (prefers-reduced-motion: reduce) {
			.mira-hero { animation: none; }
		}
		</style>
		""",
		unsafe_allow_html=True,
	)
	initialize_database()

	st.markdown(
		"""
		<div class="mira-hero">
			<div class="mira-wordmark">MIRA</div>
			<div class="mira-tagline">Markets, competitors, signals.</div>
			<p>Scan public sources, compare competitors and build a cited research brief.</p>
		</div>
		""",
		unsafe_allow_html=True,
	)

	with st.sidebar:
		st.subheader("New research")
		with st.form("research_form"):
			market = st.text_input(
				"Market or product",
				placeholder="e.g. sustainable packaging",
				key="market_input",
			)
			region = st.text_input("Region", value="North America")
			competitor_text = st.text_input(
				"Competitors", placeholder="Separate company names with commas"
			)
			submitted = st.form_submit_button(
				"Run market scan", type="primary", use_container_width=True
			)

		with st.expander("AI settings"):
			api_key = st.text_input(
				"OpenAI-compatible API key",
				value=os.getenv("MIRA_AI_API_KEY", ""),
				type="password",
				help="Used only when you request AI synthesis. Never stored in the database.",
			)
			st.caption(
				"Retrieved snippets are sent to the configured AI provider only when you "
				"generate a synthesis."
			)

		history = get_recent_runs()
		if history:
			st.divider()
			st.subheader("Saved research")
			selected_run = st.selectbox(
				"Open a previous scan",
				history,
				format_func=lambda item: f'{item["market"]} - {item["created_at"][:16]}',
				label_visibility="collapsed",
			)
			if st.button("Open selected scan", use_container_width=True):
				st.session_state["active_run_id"] = selected_run["id"]

		if submitted:
			market = market.strip()
			region = region.strip() or "Global"
			competitors = [
				name.strip()[:80]
				for name in competitor_text.split(",")
				if name.strip()
			][:5]
			if not market:
				st.error("Enter a market or product to begin.")
			else:
				try:
					with st.spinner("Searching public sources..."):
						sources = collect_sources(market[:160], region[:100], competitors)
						if not sources:
							st.error("Search returned no sources. Try a broader query.")
						else:
							run_id = save_research(market[:160], region[:100], competitors, sources)
							st.session_state["active_run_id"] = run_id
							st.rerun()
				except Exception as error:
					st.error(f"Search could not be completed: {error}")

	run_id = st.session_state.get("active_run_id")
	research = get_research(run_id) if run_id else None
	if research is None:
		feature_columns = st.columns(3)
		features = [
			("01 / DISCOVER", "Search", "Find current public sources about a market and its competitors."),
			("02 / UNDERSTAND", "Analyze", "Review relevant evidence and recurring terms across the results."),
			("03 / SHARE", "Report", "Build a cited brief you can revisit and export."),
		]
		for index, (kicker, title, description) in enumerate(features):
			with feature_columns[index]:
				with st.container(border=True, key=f"feature-card-{index}"):
					st.markdown(f'<div class="feature-kicker">{kicker}</div>', unsafe_allow_html=True)
					st.subheader(title)
					st.write(description)
		st.button(
			"Try an example: electric vehicle charging",
			on_click=lambda: st.session_state.update(
				{"market_input": "electric vehicle charging"}
			),
			key="example-search",
		)
		st.stop()

	run = research["run"]
	sources = research["sources"]
	brief = run["ai_summary"] or make_local_brief(run, sources)
	metric_market, metric_region, metric_sources = st.columns([2, 1, 1])
	metric_market.metric("Market", run["market"])
	metric_region.metric("Region", run["region"])
	metric_sources.metric("Sources", len(sources))
	st.caption(f'Research run {run["id"]}  /  {run["created_at"]}')

	brief_tab, sources_tab, history_tab = st.tabs(["Brief", "Sources", "History"])
	with brief_tab:
		col_brief, col_actions = st.columns([5, 1])
		with col_actions:
			st.download_button(
				"Download Markdown",
				make_markdown_export(run, brief, sources),
				file_name=f'mira-{run["id"]}-brief.md',
				mime="text/markdown",
				use_container_width=True,
			)
			st.download_button(
				"Download sources CSV",
				make_csv_export(sources),
				file_name=f'mira-{run["id"]}-sources.csv',
				mime="text/csv",
				use_container_width=True,
			)
		with col_brief:
			if run["ai_summary"]:
				st.markdown(brief.replace("$", r"\$"))
			else:
				render_local_brief(run, sources)

		if api_key:
			if st.button("Generate AI synthesis"):
				try:
					with st.spinner("Synthesizing retrieved evidence..."):
						brief = make_ai_brief(run, sources, api_key)
						save_ai_summary(run["id"], brief)
					st.rerun()
				except requests.RequestException as error:
					st.error(f"AI provider request failed: {error}")
				except (KeyError, IndexError, TypeError, ValueError) as error:
					st.error(f"AI provider returned an unexpected response: {error}")
		else:
			st.caption("Add an API key in AI settings to generate an AI synthesis.")

	with sources_tab:
		for index, source in enumerate(sources, 1):
			st.markdown(f'**[S{index}]**')
			st.link_button(source["title"], source["url"])
			label = source["category"]
			if source["competitor"]:
				label += f' - {source["competitor"]}'
			st.caption(f'{label}  /  {source["url"]}')
			st.write(source["snippet"] or "No search snippet was provided.")
			st.divider()

	with history_tab:
		if not history:
			st.write("Saved research runs will appear in the sidebar.")
		else:
			for item in history:
				st.markdown(
					f'**{item["market"]}** - {item["region"]}  '
					f'`{item["created_at"]}`'
				)


if __name__ == "__main__":
	main()
