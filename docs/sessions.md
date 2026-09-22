# Sessions

snowq rides the session your browser already has, so everything runs as **you**,
with your roles and ACLs. Treat the session file like a password.

## The three ways in

| Command | When to use it |
|---|---|
| `snowq -i acme login` | **Most reliable.** Opens a browser. You finish SSO/MFA, and snowq captures the cookies and `g_ck`. It uses a persistent profile (`~/.config/snowq/browser-profile`), so the IdP remembers you next time. Add `--channel chrome` or `--channel msedge` if your IdP requires a managed or compliant browser. |
| `snowq -i acme import-browser chrome` | Copies cookies out of a browser where you're already logged in (needs the `browser` extra). Works with Firefox everywhere and with Chrome on Linux/macOS. Chrome and Edge on Windows use app-bound cookie encryption, which blocks this. |
| `snowq -i acme import-cookie` | Fallback, and the only one that needs no optional extras. Paste the `Cookie` request header on stdin. |

`-i` accepts `acme`, `acme.service-now.com`, or a full URL for custom domains. You
can also set `SNOWQ_INSTANCE`.

Sessions are saved to `~/.config/snowq/sessions/<host>.session.json` (mode 0600)
and rotated cookies are written back after each run.

## Capturing the Cookie header

1. Open the instance in the browser where SSO already has you logged in.
2. `F12` → **Network** tab.
3. `Ctrl+R` to reload — a cached page may show only "provisional headers".
4. Click a request to the instance host itself (`navpage.do`, or anything under
   `/api/now/`) — not one to your IdP or a CDN.
5. **Headers** → **Request Headers** → right-click the `Cookie:` value → Copy value.
6. Save it to `cookie.txt` and redirect it in, which avoids paste and EOF quirks:
   `snowq -i acme import-cookie < cookie.txt`. Delete the file after.

Paste the whole value even if it is long; only well-formed `name=value` pairs are
kept. Do **not** use `document.cookie` from the console — `JSESSIONID` is
`HttpOnly`, so it is missing there and the session will not authenticate.

The session lasts as long as your browser session does — paste a fresh one when it
expires. `snowq login` avoids that, but needs the `login` extra.

## "the SSO session has expired"

snowq raises this whenever a request is redirected off the instance or to a login
page, which covers more than an actually-expired session. If a freshly pasted
cookie header fails straight away, test the cookies without snowq in the way:

```sh
curl -sS -i -H "Cookie: $(tr -d '\r\n' < cookie.txt)" \
  "https://acme.service-now.com/api/now/table/sys_user?sysparm_limit=1" | head -15
```

* **200 and JSON** — the cookies are good, so snowq's headers are the problem.
  The usual cause is a UA-gated instance: copy the `User-Agent` from the same
  devtools request and `export SNOWQ_USER_AGENT="<that string>"`.
* **302 to `login.do` or your IdP** — the cookies are not a working session.
  Either the copied request was to the IdP rather than the instance, or the
  instance host does not match `-i` (check the host in the browser's address bar;
  a vanity domain like `snow.corp.example` is not `corp.service-now.com`).
* **401 with `X-Is-Logged-In: true`** — the cookies are fine. ServiceNow requires
  the CSRF token on REST calls and returns the right one in
  `X-UserToken-Response`; snowq picks that up automatically.
* **401 with `X-Is-Logged-In: false`** — the session is genuinely gone; grab a
  fresh header.
