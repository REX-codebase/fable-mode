"""Static consistency checks for the Fable protocol documents."""

from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]
PROTOCOL_DOCS = (
    ROOT / "rules" / "AGENTS.md",
    ROOT / "rules" / "GEMINI.md",
    ROOT / "rules" / "fable-mode.md",
    ROOT / "skills" / "fable-mode" / "SKILL.md",
)
SCRAPER_SENTENCE_START = "Whenever external information"
LEGACY_FALLBACK_WORDING = "generic host environment search/fetch tools instead"


class ProtocolDocumentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.documents = {path: path.read_text(encoding="utf-8") for path in PROTOCOL_DOCS}

    def test_all_protocol_documents_have_the_same_scraper_fallback_policy(self):
        policies = []
        for text in self.documents.values():
            lines = [
                line[line.index(SCRAPER_SENTENCE_START) :].strip()
                for line in text.splitlines()
                if SCRAPER_SENTENCE_START in line
            ]
            self.assertEqual(len(lines), 1)
            policies.append(lines[0])

        self.assertEqual(len(set(policies)), 1)
        policy = policies[0]
        self.assertIn("Generic tools (including host search/fetch tools and web searches)", policy)
        self.assertIn("allowed **only** when Fable scrapers are unavailable or unconfigured", policy)
        self.assertIn("MUST** log the fallback rationale", policy)
        self.assertIn("auto_log_epistemic: true", policy)

    def test_mandatory_protocol_scope_and_step_five_bounds_are_consistent(self):
        for path, text in self.documents.items():
            self.assertIn("Every mandatory directive in this document applies only to non-frontier AI models", text, path.name)
            step_five = text[text.index("│ STEP 5"):text.index("│ STEP 6")]
            self.assertIn("5 iterations OR", step_five, path.name)
            self.assertIn("15 elapsed minutes", step_five, path.name)
            self.assertIn("ESCALATION_UNRESOLVED_BREAKAGES", step_five, path.name)
            self.assertIn("UNKNOWN/HYPOTHESIS", step_five, path.name)
            self.assertNotIn(LEGACY_FALLBACK_WORDING, text, path.name)

    def test_runtime_escalation_requires_ledger_entries_and_human_arbitration(self):
        for path, text in self.documents.items():
            self.assertIn("5 remediation iterations OR 15 elapsed minutes", text, path.name)
            self.assertIn("ESCALATION_UNRESOLVED_BREAKAGES", text, path.name)
            self.assertIn("[UNKNOWN]", text, path.name)
            self.assertIn("[HYPOTHESIS]", text, path.name)
            self.assertIn("request human architecture arbitration", text, path.name)

    def test_cortex_evolution_requires_a_sealed_review_and_safe_persistence_recall(self):
        for path, text in self.documents.items():
            self.assertIn("only after", text.lower(), path.name)
            self.assertIn("sealed", text.lower(), path.name)
            self.assertIn("outside the loaded skill tree", text, path.name)
            self.assertIn("authenticated or explicitly allowlisted", text, path.name)
            self.assertIn("recall", text.lower(), path.name)


if __name__ == "__main__":
    unittest.main()
