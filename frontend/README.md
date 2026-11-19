# FastAPI Project - Frontend

The frontend is built with [Vite](https://vitejs.dev/), [React](https://reactjs.org/), [TypeScript](https://www.typescriptlang.org/), [TanStack Query](https://tanstack.com/query), [TanStack Router](https://tanstack.com/router) and [Tailwind CSS](https://tailwindcss.com/).

## Requirements

- [Bun](https://bun.sh/) (recommended) or [Node.js](https://nodejs.org/)

## Quick Start

```bash
bun install
bun run dev
```

* Then open your browser at http://localhost:5173/.

Notice that this live server is not running inside Docker, it's for local development, and that is the recommended workflow. Once you are happy with your frontend, you can build the frontend Docker image and start it, to test it in a production-like environment. But building the image at every change will not be as productive as running the local development server with live reload.

Check the file `package.json` to see other available options.

### Removing the frontend

If you are developing an API-only app and want to remove the frontend, you can do it easily:

* Remove the `./frontend` directory.

* In the `compose.yml` file, remove the whole service / section `frontend`.

* In the `compose.override.yml` file, remove the whole service / section `frontend` and `playwright`.

Done, you have a frontend-less (api-only) app. 🤓

---

If you want, you can also remove the `FRONTEND` environment variables from:

* `.env`
* `./scripts/*.sh`

But it would be only to clean them up, leaving them won't really have any effect either way.

## Generate Client

### Automatically

* Activate the backend virtual environment.
* From the top level project directory, run the script:

```bash
bash ./scripts/generate-client.sh
```

* Commit the changes.

### Manually

* Start the Docker Compose stack.

* Download the OpenAPI JSON file from `http://localhost/api/openapi.json` and copy it to a new file `openapi.json` at the root of the `frontend` directory.

* To generate the frontend client, run:

```bash
bun run generate-client
```

* Commit the changes.

Notice that everytime the backend changes (changing the OpenAPI schema), you should follow these steps again to update the frontend client.

## Using a Remote API

If you want to use a remote API, you can set the environment variable `VITE_API_URL` to the URL of the remote API. For example, you can set it in the `frontend/.env` file:

```env
VITE_API_URL=https://api.my-domain.example.com
```

Then, when you run the frontend, it will use that URL as the base URL for the API.

## Code Structure

The frontend code is structured as follows:

* `frontend/src` - The main frontend code.
* `frontend/src/assets` - Static assets.
* `frontend/src/client` - The generated OpenAPI client.
* `frontend/src/components` -  The different components of the frontend.
* `frontend/src/hooks` - Custom hooks.
* `frontend/src/routes` - The different routes of the frontend which include the pages.

## End-to-End Testing with Playwright

> **Paused.** Do not run the end-to-end tests (`bun run test`, `bun run test:ui`, `bunx playwright test`) until they have their own test database.

The tests in `frontend/tests/` come from the original template and are paused while the interface is in development:

* The `Playwright Tests` workflow only runs when triggered manually from GitHub Actions.
* The `playwright` service in `compose.override.yml` only starts with `--profile e2e`.

**Why they are paused:** the tests run against the `backend` service of `compose.yml`, which loads the real `.env`. If that file points to Supabase, the tests create and delete users in the real database (`admin.spec.ts` deletes users).

### Pending work before resuming them

* **Isolated database:** run the `backend` service with a test configuration and a disposable database during the end-to-end tests, like the backend tests do with `backend/tests/test.env` and `compose.test.yml`.
* **Test credentials:** `frontend/tests/config.ts` reads `FIRST_SUPERUSER` and `FIRST_SUPERUSER_PASSWORD` from the real `.env`. Read them from a test configuration instead.
* **Tests for this project's features:** the current tests only cover what the template provides: login, sign up, password recovery, user settings and user administration. There are no tests for mails (`/items`) or questions.
* **Review against the template:** this project started from commit `38302d7` (2026-05-29) of the [Full Stack FastAPI Template](https://github.com/fastapi/full-stack-fastapi-template). List what has changed upstream in the end-to-end setup since then:

  ```bash
  git remote add template https://github.com/fastapi/full-stack-fastapi-template.git
  git fetch template
  git log --oneline 38302d7..template/master -- frontend/tests frontend/playwright.config.ts frontend/Dockerfile.playwright .github/workflows/playwright.yml compose.override.yml
  ```

* **`.env` in CI:** `.github/workflows/playwright.yml` does not create a `.env` file, and `compose.yml` does not start without one.
* **Re-enable the workflow:** add the `pull_request` trigger back to `.github/workflows/playwright.yml`, and use `main` if you add a `push` trigger.

For more information on writing and running Playwright tests, refer to the official [Playwright documentation](https://playwright.dev/docs/intro).
