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
    def test_generation_prompt_uses_dna_reference_before_task_instructions(self):
        self.assertIn("human reply dna references (read both first)", SYSTEM_PROMPT.lower())
        self.assertLess(
            SYSTEM_PROMPT.index("HUMAN REPLY DNA REFERENCES"),
            SYSTEM_PROMPT.index("TASK:"),
        )
        self.assertIn("human does not mean polished", SYSTEM_PROMPT.lower())
        self.assertIn("most specific detail", SYSTEM_PROMPT.lower())
        self.assertIn("do not use a canned phrase bank", SYSTEM_PROMPT.lower())
        # Raw sample phrases stay out of the live prompt to reduce phrase-copying.
        self.assertNotIn("this has alpha written all over it", SYSTEM_PROMPT.lower())
        self.assertNotIn("curious to see what comes from this", SYSTEM_PROMPT.lower())
        self.assertIn("20-100 characters", SYSTEM_PROMPT)
        self.assertIn("casual fragment", SYSTEM_PROMPT.lower())
        self.assertIn("zero questions is often better", SYSTEM_PROMPT.lower())
        self.assertIn("copywriter writing three engagement comments", SYSTEM_PROMPT.lower())
        self.assertIn("nice demo bro!", SYSTEM_PROMPT.lower())
        self.assertIn("ai-powered workflows...", SYSTEM_PROMPT.lower())
        self.assertIn("personal reaction, opinion, hope, concern", SYSTEM_PROMPT.lower())
        self.assertIn("game changer", SYSTEM_PROMPT.lower())
        self.assertIn("curious how...", SYSTEM_PROMPT.lower())
        self.assertIn("wow, ai account managers", SYSTEM_PROMPT.lower())
        self.assertIn("casual personal-reaction calibration", SYSTEM_PROMPT.lower())
        self.assertIn("ngl, an ai agent handling trades on its own is intriguing", SYSTEM_PROMPT.lower())
        self.assertIn("setting your own risk limits keeps control in your hands", SYSTEM_PROMPT.lower())
        self.assertIn("an nft that pays you? real utility is a big win", SYSTEM_PROMPT.lower())
        self.assertIn("casual does not mean deliberately broken", SYSTEM_PROMPT.lower())

    def test_clean_reply_removes_tag_and_em_dash(self):
        self.assertEqual(
            _clean_reply("R1: shipping fast — users can see the progress"),
            "shipping fast, users can see the progress",
        )

    def test_parse_requires_three_valid_distinct_replies(self):
        raw = """R1: this rollout actually gives users something useful
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
        raw = "1. this rollout actually gives users something useful\\n2. the wallet flow is the detail i noticed first\\n3. curious where this goes once more people try it"
        self.assertEqual(len(_parse_replies(raw)), 3)

    def test_parse_accepts_markdown_fenced_replies(self):
        raw = "```text\\nR1: this rollout actually gives users something useful\\nR2: the wallet flow is the detail i noticed first\\nR3: curious where this goes once more people try it\\n```"
        self.assertEqual(len(_parse_replies(raw)), 3)

    def test_short_reply_is_rejected(self):
        self.assertFalse(validate_reply("lol"))

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
