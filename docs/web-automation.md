# Web automation playbook

Read this when the browser tool's terse docstring isn't enough — captchas
that won't yield, logins that bounce back, two-step auth flows, or you're
deciding whether to hand off to the user via `user_takeover`.

## Captchas

The browser tool can clear most captchas on its own. **Attempt 2–3 times, then escalate.**

- **Checkboxes ("I'm not a robot")**: `click` the box. Many sites accept the click alone; some then present an image grid.
- **Image grids ("select all motorcycles")**: `snapshot` to read the prompt, `click` each matching tile, then click the verify button.
- **Text challenges**: read the question/image text from the snapshot, `type` the answer.

If 2–3 attempts don't clear it, call `user_takeover(reason="captcha couldn't be solved")`. **Do not loop further** — the agent rarely beats persistent captchas, and every attempt is paid tokens + latency.

## Login: when stored credentials fail

Escalate in order; don't retry the same credential.

1. `type(text="{{credential:NAME:username}}", ...)` and `type(text="{{credential:NAME:password}}", submit=True)` (or matching fields).
2. After submit, take a fresh `snapshot`. If the page still shows the login form, or shows an explicit error ("wrong password", "invalid", etc.), the credential is stale or wrong. **Do not try again.**
3. Call `user_takeover(is_login_takeover=True, reason="stored credential failed; please re-enter")`.

The `is_login_takeover=True` flag is load-bearing — it routes the takeover through the login-flow UI, which stores the new credentials so future runs work.

## Multi-step logins

Some sites split username and password across two pages (Google, several banks):

1. `type` username, `submit=True`. The submit triggers navigation.
2. **Take a fresh `snapshot`** — refs from the username page are invalid on the new password page.
3. `type` password using the new snapshot's refs, `submit=True`.

For OTP / 2FA codes split into multiple input boxes (e.g. 6 single-digit fields): **one `fill` call with all values**, not six separate `type` calls.

## When to bail to `user_takeover` (non-login)

- Captcha persists after 2–3 honest attempts.
- 2FA prompt asks for a code that only the user has (SMS, authenticator).
- "Verify it's you" challenge requiring phone/email confirmation.
- You cannot reach the next step after 3+ different attempts (selectors keep shifting, page is broken).

Always set `reason=` to a short user-language explanation — the user sees it when the takeover UI opens.

## `is_login_takeover=True` vs default

- `is_login_takeover=True` — login flow specifically. Stores credentials on completion. Use only when the takeover is to re-enter creds.
- `is_login_takeover=False` (default) — generic takeover. User unblocks the situation, dismisses; agent resumes.
