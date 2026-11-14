import os
import unittest

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("MIN_REPLY_CHARS", "20")
os.environ.setdefault("MAX_REPLY_CHARS", "100")

from bot.reply_engine import (
    _clean_reply,
    _parse_replies,
    SYSTEM_PROMPT,
    validate_reply,
    validate_replies,
)


class ReplyEngineTests(unittest.TestCase):
    def test_generation_prompt_is_compact_and_preserves_core_rules(self):
        prompt = SYSTEM_PROMPT.lower()
        self.assertIn("exactly three distinct, natural x replies", prompt)
        self.assertIn("react to specific details", prompt)
        self.assertIn("never invent facts or personal experience", prompt)
        self.assertIn("avoid generic praise", prompt)
        self.assertIn("at most one may be a question", prompt)
        self.assertIn("em dashes", prompt)
        self.assertIn("output exactly three lines", prompt)
        self.assertLess(len(SYSTEM_PROMPT), 700)
        # The long style reference and sample phrase bank stay out of the live prompt.
        self.assertNotIn("this has alpha written all over it", prompt)
        self.assertNotIn("curious to see what comes from this", prompt)

    def test_clean_reply_removes_tag_and_em_dash(self):
        self.assertEqual(
            _clean_reply("R1: shipping fast — users can see the progress"),
            "shipping fast, users can see the progress",
        )

    def test_validation_errors_explain_invalid_output(self):
        from bot.reply_engine import _reply_validation_errors

        errors = _reply_validation_errors([
            "this actually looks useful",
            "this actually looks useful",
            "too short",
        ])
        self.assertTrue(any("actually" in error for error in errors))
        self.assertTrue(any("distinct" in error for error in errors))
        self.assertTrue(any("characters" in error for error in errors))

    def test_candidate_parser_preserves_invalid_replies_for_diagnostics(self):
        from bot.reply_engine import _parse_reply_candidates

        candidates = _parse_reply_candidates(
            "R1: this actually looks useful to the community\\n"
            "R2: another specific observation about this launch\\n"
            "R3: this is a third distinct thought about the launch"
        )
        self.assertEqual(len(candidates), 3)
        self.assertIn("actually", candidates[0])

    def test_parse_requires_three_valid_distinct_replies(self):
        raw = """R1: this rollout really gives users something useful
R2: the wallet flow is the detail i noticed first
R3: curious where this goes once more people try it"""
        replies = _parse_replies(raw)
        self.assertEqual(len(replies), 3)
        self.assertEqual(len(set(replies)), 3)
        self.assertTrue(validate_replies(replies))

    def test_parse_accepts_same_line_r_tags(self):
        raw = "R1: this is the first useful observation R2: the number here is what caught my eye R3: ngl this part would make me look twice"
        self.assertEqual(len(_parse_replies(raw)), 3)

    def test_parse_accepts_numbered_replies(self):
        raw = "1. this rollout really gives users something useful\\n2. the wallet flow is the detail i noticed first\\n3. curious where this goes once more people try it"
        self.assertEqual(len(_parse_replies(raw)), 3)

    def test_parse_accepts_markdown_fenced_replies(self):
        raw = "```text\\nR1: this rollout really gives users something useful\\nR2: the wallet flow is the detail i noticed first\\nR3: curious where this goes once more people try it\\n```"
        self.assertEqual(len(_parse_replies(raw)), 3)

    def test_short_reply_is_rejected(self):
        self.assertFalse(validate_reply("lol"))

    def test_question_mark_must_be_at_end(self):
        self.assertFalse(validate_reply("is this live? the rollout looks useful"))
        self.assertTrue(validate_reply("the rollout looks useful, is this live?"))

    def test_disliked_filler_phrases_are_rejected(self):
        for reply in (
            "this actually gives users a useful option",
            "feels like a strong move for builders",
            "this feels off compared with the last update",
            "this or that could work for the rollout",
        ):
            self.assertFalse(validate_reply(reply))

    def test_reply_set_allows_at_most_one_question(self):
        self.assertTrue(validate_replies([
            "the wallet flow is the detail i noticed first",
            "good to see the rollout reaching more users",
            "does this support other networks yet?",
        ]))
        self.assertFalse(validate_replies([
            "does this support other networks yet?",
            "is the rollout live for everyone now?",
            "the wallet flow is the detail i noticed first",
        ]))

    def test_generic_reply_is_rejected(self):
        self.assertFalse(validate_reply("Great post"))

    def test_em_dash_is_rejected_by_validation(self):
        self.assertFalse(validate_reply("this looks clean — especially the wallet flow"))

    def test_reply_length_boundaries(self):
        self.assertTrue(validate_reply("x" * 20))
        self.assertTrue(validate_reply("x" * 100))
        self.assertFalse(validate_reply("x" * 19))
        self.assertFalse(validate_reply("x" * 101))


if __name__ == "__main__":
    unittest.main()
