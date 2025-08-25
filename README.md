# FitAI v2

## Setup

### Fitbit OAuth Redirect URL

Set the `RUN_BASE_URL` environment variable to the base URL where the application is served.
The app derives the Fitbit OAuth 2.0 redirect URL by appending `/fitbit/auth` to this value.

For example:

```bash
RUN_BASE_URL=https://example.com
```

which results in the redirect URI:

```
https://example.com/fitbit/auth
```

This exact URL — including protocol, domain, path, and port — must also be registered in the Fitbit Developer Portal. Any mismatch will cause Fitbit to return an `invalid_request` error.

