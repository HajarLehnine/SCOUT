import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app


class BusinessIntelligenceTests(unittest.TestCase):
    def sample_analysis(self):
        return {
            "market_overview": {
                "text": "Retrieved evidence indicates customer interest.",
                "source_ids": ["S1"],
            },
            "competitors": [{
                "name": "Example Energy",
                "source_ids": ["S1"],
                "swot": {
                    "strengths": [{"claim": "Offers a related product.", "source_ids": ["S1"]}],
                    "weaknesses": [{"claim": "Insufficient evidence", "source_ids": []}],
                    "opportunities": [{"claim": "Insufficient evidence", "source_ids": []}],
                    "threats": [{"claim": "Insufficient evidence", "source_ids": []}],
                },
            }],
            "score": {
                "market_demand": {
                    "points": 20,
                    "justification": "Demand is mentioned in a retrieved source.",
                    "source_ids": ["S1"],
                },
                "competition": {
                    "points": 13,
                    "justification": "One competitor is visible, but whitespace is unclear.",
                    "source_ids": ["S1"],
                },
                "profitability": {
                    "points": 12,
                    "justification": "One price point is reported.",
                    "source_ids": ["S1"],
                },
                "ease_of_entry": {
                    "points": 10,
                    "justification": "Entry barriers are not fully established.",
                    "source_ids": ["S1"],
                },
            },
            "risks": [{
                "risk": "Regulatory approval may be required.",
                "impact": "Could delay launch.",
                "likelihood": "Unknown",
                "mitigation": "Check local requirements before launch.",
                "evidence_status": "sourced",
                "source_ids": ["S1"],
            }],
            "customers": [{
                "segment": "Small businesses",
                "needs": "Need reliable energy storage.",
                "evidence_status": "sourced",
                "source_ids": ["S1"],
            }],
            "pricing": {
                "observed_prices": [{
                    "competitor": "Example Energy",
                    "price": "USD 15 / month",
                    "currency": "USD",
                    "unit": "month",
                    "region": "Japan",
                    "source_ids": ["S1"],
                }],
                "suggested_range": {
                    "low": 12,
                    "high": 18,
                    "currency": "USD",
                    "unit": "month",
                    "basis": "Test below and above the observed competitor price.",
                    "is_estimate": True,
                    "source_ids": ["S1"],
                },
                "missing_evidence": ["Local willingness-to-pay interviews."],
            },
            "opportunities": [{
                "claim": "Test a small-business pilot.",
                "evidence_status": "sourced",
                "source_ids": ["S1"],
            }],
            "recommendation": {
                "text": "Validate demand and compliance before launch.",
                "source_ids": ["S1"],
            },
            "evidence_confidence": "Low: this scan contains limited retrieved evidence.",
        }

    def test_parse_regions_deduplicates_names_and_keeps_user_order(self):
        self.assertEqual(
            app.parse_regions("Japan, Brazil, Japan, South Africa"),
            ["Japan", "Brazil", "South Africa"],
        )

    def test_collect_sources_tags_country_and_research_category(self):
        result = {
            "href": "https://example.test/market",
            "title": "Market evidence",
            "body": "Evidence snippet",
        }
        with patch.object(app, "search_web", return_value=[result]) as search_web:
            sources = app.collect_sources(
                "solar batteries", ["Japan", "Brazil"], ["Example Energy"]
            )

        self.assertEqual(
            {source["region"] for source in sources},
            {"Japan", "Brazil"},
        )
        self.assertTrue(
            {"Market", "Customer and pricing", "Risk", "Competitor"}.issubset(
                {source["category"] for source in sources}
            )
        )
        self.assertEqual(search_web.call_count, 10)
        self.assertEqual(
            sum("top companies competitors" in call.args[0] for call in search_web.call_args_list),
            2,
        )

    def test_collect_sources_rejects_more_than_five_regions(self):
        with self.assertRaisesRegex(ValueError, "no more than five"):
            app.collect_sources(
                "solar batteries",
                ["Japan", "Brazil", "India", "France", "Kenya", "Canada"],
                [],
            )

    def test_web_analysis_requires_score_and_retrieved_citations(self):
        sources = [{"title": "Source"}]
        analysis = "Opportunity Score: 72/100\nDemand evidence supports this [S1]."
        self.assertEqual(
            app.verify_web_analysis(analysis, sources, require_score=True),
            analysis,
        )

    def test_csv_export_includes_each_source_region(self):
        csv_export = app.make_csv_export([{
            "region": "Japan",
            "category": "Market",
            "competitor": "",
            "title": "Market evidence",
            "url": "https://example.test/market",
            "snippet": "Evidence",
        }])

        self.assertIn("region,category,competitor,title,url,snippet", csv_export)
        self.assertIn("Japan,Market,,Market evidence", csv_export)

    def test_web_analysis_rejects_unknown_citation(self):
        with self.assertRaisesRegex(ValueError, "not retrieved"):
            app.verify_web_analysis(
                "Opportunity Score: 72/100\nClaim [S2].",
                [{"title": "Source"}],
                require_score=True,
            )

    def test_web_analysis_rejects_citation_not_in_model_context(self):
        with self.assertRaisesRegex(ValueError, "not retrieved"):
            app.verify_web_analysis(
                "Opportunity Score: 72/100\nClaim [S2].",
                [{"title": "Source"}],
                require_score=True,
                source_reference_ids=["S1"],
            )

    def test_web_analysis_rejects_missing_or_invalid_score(self):
        sources = [{"title": "Source"}]
        with self.assertRaisesRegex(ValueError, "valid opportunity score"):
            app.verify_web_analysis("Claim [S1].", sources, require_score=True)
        with self.assertRaisesRegex(ValueError, "valid opportunity score"):
            app.verify_web_analysis(
                "Opportunity Score: 101/100\nClaim [S1].",
                sources,
                require_score=True,
            )

    def test_structured_analysis_calculates_transparent_score_and_sections(self):
        result = app.format_structured_analysis(self.sample_analysis(), ["S1"])

        self.assertIn("**Opportunity Score: 55/100**", result)
        self.assertIn("Market demand: 20/30", result)
        self.assertIn("Competitive position: 13/25", result)
        self.assertIn("Profitability: 12/25", result)
        self.assertIn("Ease of entry: 10/20", result)
        self.assertIn("Competitor analysis and SWOT", result)
        self.assertIn("Risk analysis", result)
        self.assertIn("Target customers and needs", result)
        self.assertIn("Observed source price:", result)
        self.assertIn("Example Energy", result)
        self.assertIn("USD 15 / month", result)
        self.assertIn("Test range (estimate, not observed)", result)

    def test_structured_analysis_localizes_labels_and_preserves_source_claims(self):
        result = app.format_structured_analysis(
            self.sample_analysis(), ["S1"], "French"
        )

        self.assertIn("Vue d’ensemble du marché mondial", result)
        self.assertIn("Score d’opportunité", result)
        self.assertIn("Analyse des concurrents et SWOT", result)
        self.assertIn("Example Energy", result)
        self.assertIn("[S1]", result)

    def test_pdf_question_prompt_uses_selected_language(self):
        matches = [{
            "text": "Revenue is described on page 2.",
            "metadata": {"file_name": "Annual Report.pdf", "page_number": 2},
        }]
        response = unittest.mock.Mock()
        response.json.return_value = {
            "choices": [{"message": {"content": "Le revenu est décrit [P1]."}}]
        }

        with patch.object(app.requests, "post", return_value=response) as post:
            answer = app.answer_pdf_question(
                "What does this say?", matches, "test-key", "French"
            )

        self.assertIn("[P1]", answer)
        prompt = post.call_args.kwargs["json"]["messages"][0]["content"]
        self.assertIn("French", prompt)

    def test_structured_analysis_rejects_out_of_range_score(self):
        analysis = self.sample_analysis()
        analysis["score"]["market_demand"]["points"] = 31

        with self.assertRaisesRegex(ValueError, "0 to 30"):
            app.format_structured_analysis(analysis, ["S1"])

    def test_nonzero_score_requires_cited_evidence(self):
        analysis = self.sample_analysis()
        analysis["score"]["profitability"]["source_ids"] = []

        with self.assertRaisesRegex(ValueError, "supporting source citation"):
            app.format_structured_analysis(analysis, ["S1"])

    def test_pricing_range_requires_citation_and_estimate_label(self):
        analysis = self.sample_analysis()
        analysis["pricing"]["suggested_range"]["is_estimate"] = False

        with self.assertRaisesRegex(ValueError, "labeled, valid estimate"):
            app.format_structured_analysis(analysis, ["S1"])

    def test_pricing_range_rejects_non_finite_numbers(self):
        analysis = self.sample_analysis()
        analysis["pricing"]["suggested_range"]["low"] = float("nan")

        with self.assertRaisesRegex(ValueError, "labeled, valid estimate"):
            app.format_structured_analysis(analysis, ["S1"])

    def test_missing_price_evidence_does_not_generate_a_price_range(self):
        analysis = self.sample_analysis()
        analysis["pricing"]["observed_prices"] = []
        analysis["pricing"]["suggested_range"] = None

        result = app.format_structured_analysis(analysis, ["S1"])

        self.assertIn("No actual competitor prices were found", result)
        self.assertIn("No sourced test-price range is available", result)

    def test_uncited_observed_price_is_rejected(self):
        analysis = self.sample_analysis()
        analysis["pricing"]["observed_prices"][0]["source_ids"] = []

        with self.assertRaisesRegex(ValueError, "supporting source citation"):
            app.format_structured_analysis(analysis, ["S1"])

    def test_analysis_rejects_unknown_swat_citation(self):
        analysis = self.sample_analysis()
        analysis["competitors"][0]["swot"]["strengths"][0]["source_ids"] = ["S2"]

        with self.assertRaisesRegex(ValueError, "not provided to the model"):
            app.format_structured_analysis(analysis, ["S1"])

    def test_initialize_database_migrates_existing_tables(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "legacy.sqlite3"
            connection = sqlite3.connect(database_path)
            connection.executescript(
                """
                CREATE TABLE research_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    market TEXT NOT NULL,
                    region TEXT NOT NULL,
                    competitors TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    ai_summary TEXT NOT NULL DEFAULT '',
                    output_language TEXT NOT NULL DEFAULT 'French',
                    ai_business_plan TEXT NOT NULL DEFAULT ''
                );
                INSERT INTO research_runs (market, region, competitors, ai_summary, output_language, ai_business_plan)
                VALUES ('Solar', 'France', '', 'Résumé', 'French', 'Plan');
                CREATE TABLE sources (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    category TEXT NOT NULL,
                    competitor TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL,
                    url TEXT NOT NULL,
                    snippet TEXT NOT NULL
                );
                """
            )
            connection.close()

            with patch.object(app, "DATABASE_PATH", database_path):
                app.initialize_database()

            connection = sqlite3.connect(database_path)
            run_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(research_runs)")
            }
            source_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(sources)")
            }
            generated_languages = connection.execute(
                "SELECT ai_summary_language, ai_business_plan_language "
                "FROM research_runs WHERE id = 1"
            ).fetchone()
            connection.close()

        self.assertIn("ai_business_plan", run_columns)
        self.assertIn("output_language", run_columns)
        self.assertIn("ai_summary_language", run_columns)
        self.assertIn("ai_business_plan_language", run_columns)
        self.assertIn("region", source_columns)
        self.assertEqual(generated_languages, ("French", "French"))

    def test_saved_research_keeps_region_and_generated_plan(self):
        source = {
            "category": "Market",
            "competitor": "",
            "region": "Japan",
            "title": "Market evidence",
            "url": "https://example.test/market",
            "snippet": "Evidence snippet",
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            with patch.object(
                app,
                "DATABASE_PATH",
                Path(temporary_directory) / "research.sqlite3",
            ):
                app.initialize_database()
                run_id = app.save_research(
                    "Solar batteries", "Japan", [], [source]
                )
                app.save_ai_business_plan(run_id, "Plan [S1].", "French")
                app.save_ai_summary(run_id, "Résumé [S1].", "French")
                research = app.get_research(run_id)

        self.assertEqual(research["sources"][0]["region"], "Japan")
        self.assertEqual(research["run"]["ai_business_plan"], "Plan [S1].")
        self.assertEqual(research["run"]["ai_summary_language"], "French")
        self.assertEqual(research["run"]["ai_business_plan_language"], "French")

    def test_ai_analysis_prompt_uses_sources_and_verifies_score_citations(self):
        run = {
            "market": "solar demand",
            "region": "Japan",
            "competitors": "",
            "output_language": "English",
        }
        sources = [{
            "id": 1,
            "category": "Market",
            "competitor": "",
            "region": "Japan",
            "title": "Solar demand outlook",
            "snippet": "Demand evidence",
            "url": "https://example.test/solar",
        }]
        response = unittest.mock.Mock()
        response.json.return_value = {
            "choices": [{
                "message": {
                    "content": json.dumps(self.sample_analysis())
                }
            }]
        }
        with patch.object(app.requests, "post", return_value=response) as post:
            analysis = app.make_ai_brief(run, sources, "test-key")

        self.assertIn("Opportunity Score: 55/100", analysis)
        prompt = post.call_args.kwargs["json"]["messages"][0]["content"]
        self.assertIn("market_demand 0-30", prompt)
        self.assertIn("observed_prices", prompt)
        self.assertIn(
            "Identify competitors only from retrieved competitor evidence",
            prompt,
        )

    def test_business_plan_prompt_uses_original_source_ids(self):
        run = {
            "market": "solar demand",
            "region": "Japan",
            "competitors": "",
            "output_language": "English",
        }
        sources = [
            {
                "id": 5,
                "category": "Market",
                "competitor": "",
                "region": "Japan",
                "title": "Unrelated local news",
                "snippet": "Unrelated details",
                "url": "https://example.test/news",
            },
            {
                "id": 9,
                "category": "Risk",
                "competitor": "",
                "region": "Japan",
                "title": "Solar demand outlook",
                "snippet": "Demand evidence",
                "url": "https://example.test/solar",
            },
        ]
        response = unittest.mock.Mock()
        response.json.return_value = {
            "choices": [{
                "message": {"content": "Plan based on evidence [S2]."}
            }]
        }
        with patch.object(app.requests, "post", return_value=response) as post:
            plan = app.make_ai_business_plan(run, sources, "test-key")

        self.assertIn("[S2]", plan)
        prompt = post.call_args.kwargs["json"]["messages"][1]["content"]
        self.assertIn("[S2] Region: Japan", prompt)

    def test_business_plan_pdf_is_a_pdf_with_cited_source_links(self):
        run = {"market": "Solar batteries", "region": "Japan"}
        plan = "# Executive Summary\nLaunch a pilot based on evidence [S1]."
        sources = [{
            "title": "Market evidence",
            "url": "https://example.test/market?ref=source",
            "region": "Japan",
        }]

        pdf = app.make_business_plan_pdf(run, plan, sources)

        self.assertTrue(pdf.startswith(b"%PDF-"))
        self.assertIn(b"example.test", pdf)


if __name__ == "__main__":
    unittest.main()
