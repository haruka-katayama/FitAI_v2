# FitAI v2
## Setup
### Health Planet OAuth Configuration
- `HP_REDIRECT_URI`: URL for the Health Planet OAuth callback. Set this to the application's `/healthplanet/auth`
  endpoint and ensure it matches the URL registered in the Health Planet Developer Portal.

### Fitbit OAuth Redirect URL
Set the `RUN_BASE_URL` environment variable to the base URL where the application is served.
The app derives the Fitbit OAuth 2.0 redirect URL by appending `/fitbit/auth` to this value.
For example:
```bash
RUN_BASE_URL=https://example.com