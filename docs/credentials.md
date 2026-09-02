# Using stored credentials

Credentials are registered through the `credentials` tool and stored encrypted. You never see their values — you reference them by name, and the reference is resolved at execution time.

## One reference syntax

    {{credential:NAME}}          the credential's only field
    {{credential:NAME:FIELD}}    one field of a multi-field credential

`credentials(action='check', credential_name=...)` lists the fields a credential holds. A `login` credential holds `username` and `password`, so it must always name a field — a bare reference would be ambiguous and is rejected.

## Where references work

The same reference works in both consumers. Which one you use is your choice at the time, not a property of the credential.

**curl** — anywhere in the command's arguments:

    curl -s https://api.example.com/endpoint \
      -H "Authorization: Bearer {{credential:my-api}}" \
      -d '{"query": "hello"}'

**browser** — as the typed text, or as a fill value:

    browser type ref=e5 text="{{credential:site-login:username}}"
    browser type ref=e6 text="{{credential:site-login:password}}" submit=True

For complex API processing, use curl for the authenticated call and pipe to python:

    curl -s https://api.example.com/data \
      -H "Authorization: Bearer {{credential:my-api}}" | \
      python3 -c "import json, sys; data = json.load(sys.stdin); print(data['result'])"

## Binding

A credential registered with a `base_url` only resolves against that origin — in curl, the command must target it; in the browser, the page must already be on it. Navigate first, then inject. This holds in both consumers, so a secret cannot be sent to a site it wasn't registered for.

## CLI tools

CLI credentials need no reference at all. When you run a registered CLI command, the credential is already in the configured environment variable.

A CLI credential is for that CLI only — it cannot be referenced in curl or typed into a page. Don't repurpose one for a website: leave it alone and request a separate credential bound to the site. A binding cannot be edited after creation, so changing one means deleting the credential and requesting it again, which also discards the stored secret.
