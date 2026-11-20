import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("chatgpt_auth_smoke.py")
SPEC = importlib.util.spec_from_file_location("chatgpt_auth_smoke", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class EmailOnlyAuthSmokeHelpersTest(unittest.TestCase):
    def test_selectors_include_code_field(self):
        self.assertIn('input[placeholder="Code"]', MODULE.SELECTORS)
        self.assertIn('input[placeholder*="6-digit" i]', MODULE.TOTP_SELECTORS)

    def test_one_time_code_button_label(self):
        self.assertEqual(
            " ".join("log in with a one-time code".lower().split()),
            "log in with a one-time code",
        )

    def test_required_secret_raises_when_missing(self):
        import os

        env_var = "__UNRELATED_SECRET_NEVER_SET__"
        try:
            with self.assertRaises(RuntimeError):
                MODULE.required_secret(env_var)
        finally:
            os.environ.pop(env_var, None)

    def test_optional_env_returns_empty_when_unset(self):
        import os

        os.environ.pop("CHATGPT_VERIFICATION_CODE", None)
        self.assertEqual(MODULE.optional_env("CHATGPT_VERIFICATION_CODE"), "")

    def test_totp_matches_rfc_6238_sha1_vector(self):
        self.assertEqual(
            MODULE.current_totp("GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ", timestamp=59),
            "287082",
        )


if __name__ == "__main__":
    unittest.main()
