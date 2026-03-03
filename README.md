# Liquibase → ERD

Run a Liquibase changelog against PostgreSQL, then view and export the resulting database schema as an **ERD diagram** in **draw.io** format (editable in [diagrams.net](https://app.diagrams.net/) or the draw.io desktop app).

## Quick start

1. **Start the stack**

   ```bash
   docker compose up --build
   ```

2. **Open the app**

   - Go to [http://localhost:5000](http://localhost:5000).

3. **Upload a Liquibase changelog**

   - Choose a root changelog file (`.xml`, `.yaml`, or `.yml`).
   - Click **Run Liquibase & generate ERD**.

4. **View and export the ERD**

   - The ERD is shown in an embedded draw.io editor.
   - Use **Download .drawio file** to save a `.drawio` file you can open and edit in draw.io / diagrams.net.

## Services

| Service   | Port  | Description                    |
|----------|-------|--------------------------------|
| **app**  | 5000  | Web UI: upload changelog, run Liquibase, view/download ERD |
| **postgres** | 5432 | PostgreSQL 16 (user `appuser`, db `appdb`) |

## Sample changelog

A sample Liquibase changelog is in `sample/changelog.xml` (creates `users`, `posts`, and `comments` with foreign keys). Upload that file to try the flow.

## Requirements

- Docker and Docker Compose
- Liquibase changelog that targets PostgreSQL (e.g. standard Liquibase XML/YAML)

## Notes

- The app runs Liquibase against the `public` schema. Tables in other schemas are still introspected and included in the ERD.
- For changelogs that use `<include file="..."/>`, the included files must be relative to the root changelog; the current UI supports a single file upload, so either use one combined changelog or host the set of files elsewhere and reference them (e.g. via a wrapper that provides the same layout).
- The generated `.drawio` file is standard draw.io/mxGraph XML and can be opened in [app.diagrams.net](https://app.diagrams.net/), the draw.io VS Code extension, or the draw.io desktop app.
