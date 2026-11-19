import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("chatgpt_auth_smoke.py")
SPEC = importlib.util.spec_from_file_location("chatgpt_auth_smoke", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class AuthSmokeHelpersTest(unittest.TestCase):
    def test_totp_matches_rfc_6238_sha1_vector(self):
        self.assertEqual(
            MODULE.current_totp("GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ", timestamp=59),
            "287082",
        )

    def test_password_sign_in_labels_are_exact(self):
        self.assertTrue(MODULE.is_password_action_text(" Continue with password "))
        self.assertTrue(MODULE.is_password_action_text("Use   password"))
        self.assertFalse(MODULE.is_password_action_text("Forgot password?"))
        self.assertFalse(MODULE.is_password_action_text("Reset password"))


if __name__ == "__main__":
    unittest.main()
