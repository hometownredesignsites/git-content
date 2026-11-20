# ChatGPT authentication smoke test

The GitHub Actions job launches normal headed Chromium under Xvfb, attaches Playwright over Chromium's local debugging port, and stops when ChatGPT's signed-in profile control is visible. It does not send a prompt, upload a file, or save browser cookies beyond the temporary run.

## Flow

1. Enter the account email (`CHATGPT_LOGIN_EMAIL`). ChatGPT emails a one-time verification code.
2. If a code is supplied (workflow_dispatch `verification_code` input, or `CHATGPT_VERIFICATION_CODE`), enter it to complete sign-in.
3. If no code is supplied, the run stops cleanly with status `waiting_for_code` so a follow-up `workflow_dispatch` run can complete sign-in with the code.
4. If ChatGPT presents a TOTP/authenticator screen instead, `CHATGPT_TOTP_SECRET` generates the six-digit code.

The `auth-chatgpt` environment can provide `CHATGPT_LOGIN_EMAIL`. If it is not set, the smoke test falls back to `hometownredesign1@yahoo.com`. `CHATGPT_TOTP_SECRET` is used when ChatGPT presents a TOTP/authenticator screen instead of a code screen.

The workflow runs on pushes that change files under this directory or its workflow file. `workflow_dispatch` is also defined, but GitHub requires the workflow file to exist on the default branch before its manual Run workflow button is available.

Each run's artifact contains a result JSON and viewport screenshots for the home page, email/code/TOTP checkpoints, and the final profile check. Screenshots mask input fields, navigation/sidebar content, the profile control, and visible text matching the account email.
