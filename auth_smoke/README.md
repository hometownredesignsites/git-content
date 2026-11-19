# ChatGPT authentication smoke test

The GitHub Actions job launches normal headed Chromium under Xvfb, attaches Playwright over Chromium's local debugging port, and stops when ChatGPT's signed-in profile control is visible. It does not send a prompt or upload a file.

The `auth-chatgpt` environment must provide `CHATGPT_LOGIN_EMAIL`, `CHATGPT_LOGIN_PASSWORD`, and `CHATGPT_TOTP_SECRET`. The TOTP value is the base32 authenticator setup secret. Restrict the environment to trusted maintainers and the `auth-chatgpt` branch.

The workflow runs on pushes that change files under this directory or its workflow file. `workflow_dispatch` is also defined, but GitHub requires the workflow file to exist on the default branch before its manual Run workflow button is available.

Each run's artifact contains a result JSON and viewport screenshots for the home page, email/password/TOTP checkpoints, and the final profile check. Screenshots mask input fields, navigation/sidebar content, the profile control, and visible text matching the account email.
